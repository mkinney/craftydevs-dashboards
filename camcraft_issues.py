#!/usr/bin/env python3
"""CamCraft issues board: one static page built from `gh` only (no AI).

Open issues by priority with a keyword filter and priority / state checkboxes, plus what opened and closed today
(UTC, the same day boundary as `gh ... --search "closed:YYYY-MM-DD"`). Runs from cron every few minutes.
Environment: CAMCRAFT_ISSUES_OUT (default ~/dashboards/camcraft/issues.html), CAMCRAFT_ISSUES_DEST (an rsync target;
empty = keep the page local).
"""
import datetime as dt, html, json, os, subprocess, sys

R = "NeoTech/Camcraft"
GH = next((p for p in ("/opt/homebrew/bin/gh", "/usr/local/bin/gh") if os.path.exists(p)), "gh")
OUT = os.path.expanduser(os.environ.get("CAMCRAFT_ISSUES_OUT", "~/dashboards/camcraft/issues.html"))
DEST = os.environ.get("CAMCRAFT_ISSUES_DEST", "")
PRIOS = ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P?", "none"]
PDESC = {
    "P1": "unsafe or wrong output: a gouge or collision that passes, wrong posted G-code, a crash, data loss",
    "P2": "main is broken, or the last release has a regression with no workaround",
    "P3": "wrong behaviour a user hits, with a workaround",
    "P4": "work the maintainer asked for, for the next cut",
    "P5": "the agent surface and tooling keep up with what shipped",
    "P6": "accepted enhancements, not scheduled",
    "P7": "owed polish and small fixes",
    "P8": "larger ideas that need design or research before code",
    "P9": "someday",
    "P?": "paused by the maintainer",
    "none": "not triaged yet",
}
STATES = [("free", "free to pick"), ("claimed", "claimed: being worked"), ("in-review", "in review: a PR is open"),
          ("blocked", "blocked"), ("needs-research", "needs research")]


def gh(*args):
    r = subprocess.run([GH, *args], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:300])
    return json.loads(r.stdout) if r.stdout.strip() else []


def esc(s):
    return html.escape(str(s or ""), quote=True)


def ago(ts):
    s = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))).total_seconds()
    return f"{int(s // 60)}m" if s < 3600 else f"{int(s // 3600)}h" if s < 86400 else f"{int(s // 86400)}d"


def publish(path, dest):
    if not dest:
        print(f"wrote {path} (set CAMCRAFT_ISSUES_DEST to publish it)")
        return 0
    return subprocess.run(["rsync", "-q", "-e", "ssh -o BatchMode=yes", path, dest], capture_output=True,
                          text=True, timeout=60).returncode


F = "number,title,author,labels,assignees,createdAt,updatedAt,closedAt,url,stateReason"
today = dt.datetime.now(dt.timezone.utc).date().isoformat()
open_issues = gh("issue", "list", "-R", R, "--state", "open", "--limit", "2000", "--json", F)
closed_today = gh("issue", "list", "-R", R, "--state", "closed", "--limit", "500", "--search", f"closed:{today}", "--json", F)
opened_today = [i for i in open_issues + closed_today if i["createdAt"][:10] == today]
prs_closed_today = gh("pr", "list", "-R", R, "--state", "closed", "--limit", "500", "--search", f"closed:{today}",
                      "--json", "number,mergedAt")
prs_open = gh("pr", "list", "-R", R, "--state", "open", "--limit", "500", "--json", "number,isDraft")


def labels(i):
    return [l["name"] for l in i["labels"]]


def prio(i):
    p = [x for x in labels(i) if x in PRIOS]
    return min(p, key=PRIOS.index) if p else "none"


def state(i):
    ls = labels(i)
    for s in ("in-review", "blocked", "claimed", "needs-research"):
        if s in ls:
            return s
    return "free"


def lane(i):
    ls = labels(i)
    return "enhancement" if "enhancement" in ls and "bug" not in ls else "bug"


def card(i):
    ls = labels(i)
    p, s = prio(i), state(i)
    tags = "".join(f'<span class="tag">{esc(x)}</span>' for x in ls if x.startswith(("area:", "effort:")))
    who = ", ".join(a["login"] for a in i["assignees"])
    src = ' <span class="tag agent">agent</span>' if "source:agent" in ls else ""
    text = f'#{i["number"]} {i["title"]} {i["author"]["login"]} {who} {" ".join(ls)}'.lower()
    return (f'<div class="card" data-p="{esc(p)}" data-s="{s}" data-t="{esc(text)}">'
            f'<a class="num" href="{esc(i["url"])}">#{i["number"]}</a> <span class="pill p-{esc(p).replace("?", "q")}">{esc(p)}</span> '
            f'<span class="st st-{s}">{esc(s)}{(" · " + esc(who)) if who and s in ("claimed", "in-review") else ""}</span> '
            f'<a class="ttl" href="{esc(i["url"])}">{esc(i["title"])}</a>{src}<div class="meta">{tags} '
            f'<span class="mut">{lane(i)} · by {esc(i["author"]["login"])} · opened {ago(i["createdAt"])} ago · '
            f'updated {ago(i["updatedAt"])} ago</span></div></div>')


groups = {p: sorted([i for i in open_issues if prio(i) == p], key=lambda i: i["createdAt"]) for p in PRIOS}
sections = "".join(
    f'<section data-p="{esc(p)}"><h2><span class="pill p-{esc(p).replace("?", "q")}">{esc(p)}</span> {esc(PDESC[p])} '
    f'<span class="mut">({len(groups[p])})</span></h2>{"".join(card(i) for i in groups[p])}</section>'
    for p in PRIOS if groups[p])
count = lambda f: sum(1 for i in open_issues if f(i))
merged_today = sum(1 for p in prs_closed_today if p.get("mergedAt"))
kpis = [
    (len(open_issues), "open issues"),
    (count(lambda i: prio(i) in ("P1", "P2")), "open P1/P2 (these hold a cut)"),
    (count(lambda i: state(i) == "free" and prio(i) not in ("P?", "none")), "free to pick"),
    (count(lambda i: prio(i) == "none"), "untriaged"),
    (len(opened_today), "issues opened today (UTC)"),
    (len(closed_today), "issues closed today (UTC)"),
    (len(prs_open), f"open PRs ({sum(1 for p in prs_open if p['isDraft'])} drafts)"),
    (len(prs_closed_today), f"PRs closed today ({merged_today} merged)"),
]
closed_list = "".join(
    f'<li><a href="{esc(i["url"])}">#{i["number"]}</a> {esc(i["title"])} <span class="mut">'
    f'{"not planned" if i.get("stateReason") == "NOT_PLANNED" else "completed"} · {ago(i["closedAt"])} ago</span></li>'
    for i in sorted(closed_today, key=lambda i: i["closedAt"], reverse=True))
pchecks = "".join(f'<label class="fp" title="{esc(PDESC[p])}"><input type="checkbox" value="{esc(p)}">{esc(p)}</label>' for p in PRIOS)
schecks = "".join(f'<label class="fs" title="{esc(t)}"><input type="checkbox" value="{s}">{s}</label>' for s, t in STATES)
now = dt.datetime.now(dt.timezone.utc)
page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>CamCraft issues</title><style>
:root{{--bg:#f6f7f9;--card:#fff;--fg:#1d2330;--mut:#667085;--line:#e3e6eb;--acc:#2f6fde}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#0f1218;--card:#171b23;--fg:#e6e9ef;--mut:#98a2b3;--line:#2a303b;--acc:#6ea0ff}}}}
:root[data-theme=dark]{{--bg:#0f1218;--card:#171b23;--fg:#e6e9ef;--mut:#98a2b3;--line:#2a303b;--acc:#6ea0ff}}
body{{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:16px}}a{{color:var(--acc);text-decoration:none}}a:hover{{text-decoration:underline}}
header{{display:flex;flex-wrap:wrap;gap:12px;align-items:baseline}}h1{{margin:0;font-size:22px}}.mut{{color:var(--mut)}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:14px 0}}
.kpis div{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px}}.kpis b{{display:block;font-size:22px}}.kpis span{{color:var(--mut);font-size:12px}}
.bar{{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center;margin:10px 0}}#fclear{{padding:4px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg);cursor:pointer}}
#fq{{flex:1 1 220px;padding:6px 8px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg)}}
.fp,.fs{{font-size:12px;white-space:nowrap}}h2{{font-size:15px;margin:18px 0 6px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 10px;margin:6px 0}}
.num{{font-weight:600}}.ttl{{color:var(--fg)}}.meta{{margin-top:3px;font-size:12px}}
.pill{{display:inline-block;border-radius:6px;padding:0 6px;font-size:12px;font-weight:600;color:#fff;background:#8a94a3}}
.p-P1{{background:#c62828}}.p-P2{{background:#e0571a}}.p-P3{{background:#d39200}}.p-P4{{background:#2f6fde}}.p-P5{{background:#6b4fd8}}.p-P6{{background:#1f9d55}}
.st{{font-size:12px;border:1px solid var(--line);border-radius:6px;padding:0 6px}}.st-free{{color:#1f9d55}}.st-claimed{{color:#d39200}}.st-in-review{{color:var(--acc)}}.st-blocked{{color:#c62828}}
.tag{{display:inline-block;font-size:11px;border:1px solid var(--line);border-radius:5px;padding:0 5px;margin-right:4px;color:var(--mut)}}.tag.agent{{font-size:11px}}
details{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 12px;margin:8px 0}}details li{{margin:2px 0}}
.gh svg{{width:20px;height:20px;fill:var(--mut)}}
</style></head><body><main>
<header><h1>CamCraft issues</h1><a href="./">PR board</a><a href="stats.html">Stats</a>
<span class="mut">updated {now:%Y-%m-%d %H:%M} UTC (every 5 minutes)</span>
<a class="gh" href="https://github.com/NeoTech/Camcraft/issues" aria-label="Issues on GitHub"><svg viewBox="0 0 16 16"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg></a></header>
<div class="kpis">{"".join(f"<div><b>{n:,}</b><span>{esc(t)}</span></div>" for n, t in kpis)}</div>
<details><summary>Issues closed today (UTC): {len(closed_today)}</summary><ul>{closed_list or "<li class='mut'>none yet</li>"}</ul></details>
<div class="bar"><input id="fq" type="search" placeholder="Filter: #number, words in the title, author, assignee, label" aria-label="Filter issues">{pchecks}</div>
<div class="bar">{schecks}<button id="fclear" type="button">Clear</button><span id="fcount" class="mut"></span></div>
{sections}
</main><script>
const q=document.getElementById('fq'),K='cc-issues-f2';
const PB=[...document.querySelectorAll('.fp input')],SB=[...document.querySelectorAll('.fs input')];
const on=bs=>bs.filter(b=>b.checked).map(b=>b.value);
function f(){{const t=q.value.trim().toLowerCase().split(/\\s+/).filter(Boolean),P=on(PB),S=on(SB);
 let n=0,all=0;document.querySelectorAll('.card').forEach(c=>{{all++;const ok=(!P.length||P.includes(c.dataset.p))&&(!S.length||S.includes(c.dataset.s))&&t.every(w=>c.dataset.t.includes(w));c.hidden=!ok;n+=ok}});
 document.querySelectorAll('section').forEach(s=>{{s.hidden=![...s.querySelectorAll('.card')].some(c=>!c.hidden)}});
 document.getElementById('fcount').textContent=(t.length||P.length||S.length)?` showing ${{n}} of ${{all}} issues`:'';
 try{{localStorage.setItem(K,JSON.stringify({{q:q.value,P,S}}))}}catch(e){{}}}}
try{{const v=JSON.parse(localStorage.getItem(K)||'null');if(v){{q.value=v.q||'';PB.forEach(b=>b.checked=(v.P||[]).includes(b.value));SB.forEach(b=>b.checked=(v.S||[]).includes(b.value))}}}}catch(e){{}}
const u=new URLSearchParams(location.search);if(u.get('q')!==null)q.value=u.get('q');if(u.get('p'))PB.forEach(b=>b.checked=u.get('p').split(',').includes(b.value));
document.getElementById('fclear').onclick=()=>{{q.value='';PB.concat(SB).forEach(b=>b.checked=false);f()}};
q.addEventListener('input',f);PB.concat(SB).forEach(x=>x.addEventListener('change',f));f();
</script></body></html>"""
os.makedirs(os.path.dirname(OUT), exist_ok=True)
open(OUT + ".tmp", "w").write(page)
os.replace(OUT + ".tmp", OUT)
sys.exit(publish(OUT, DEST))
