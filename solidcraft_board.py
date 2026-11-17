#!/usr/bin/env python3
"""SolidCraft PR board: one static public page from `gh` only (no AI), every 15 min from cron (user, 2026-11-16).
Publishes https://craftydevs.org/solidcraft/status/ . Columns follow SolidCraft's own labels and GitHub's review state.
Shows PRs active in the last 14 days by default; a button shows all open PRs. Links to the SolidCraft leaderboard."""
import datetime as dt, html, json, os, subprocess, sys

R = "tangency-labs/solidcraft"
GH = next((p for p in ("/opt/homebrew/bin/gh", "/usr/local/bin/gh") if os.path.exists(p)), "gh")
OUT = os.path.expanduser(os.environ.get("SOLIDCRAFT_BOARD_OUT", "~/dashboards/solidcraft/index.html"))
DEST = os.environ.get("SOLIDCRAFT_BOARD_DEST", "")


def publish(path: str, dest: str) -> int:
    """Copy the page to DEST (an rsync target such as user@host:public_html/status/index.html); no DEST = keep local."""
    if not dest:
        print(f"wrote {path} (set the DEST variable to publish it)")
        return 0
    return subprocess.run(["rsync", "-q", "-e", "ssh -o BatchMode=yes", path, dest], capture_output=True, text=True,
                          timeout=60).returncode

def gh(*a):
    r = subprocess.run([GH, *a], capture_output=True, text=True, timeout=300)
    if r.returncode:
        raise RuntimeError(r.stderr[:300])
    return json.loads(r.stdout or "[]")


def ago(ts):
    t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    s = (dt.datetime.now(dt.timezone.utc) - t).total_seconds()
    return f"{int(s // 60)}m" if s < 3600 else (f"{int(s // 3600)}h" if s < 86400 else f"{int(s // 86400)}d")


def days_since(ts):
    t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return (dt.datetime.now(dt.timezone.utc) - t).days


esc = lambda s: html.escape(str(s or ""))
prs = gh("pr", "list", "-R", R, "--state", "open", "--limit", "1000", "--json",
         "number,title,author,isDraft,labels,mergeable,reviewDecision,updatedAt,url,baseRefName,closingIssuesReferences")
PRIOS = ["P0", "P1", "P2", "P3"]
ISSUE_PRIO: dict[int, str] = {}
for _p in PRIOS:                                  # issues by priority label (search, one call per level)
    try:
        for i in gh("issue", "list", "-R", R, "--state", "all", "--limit", "1000", "--label", f"priority:{_p}",
                    "--json", "number"):
            ISSUE_PRIO.setdefault(i["number"], _p)
    except Exception:
        pass


def pr_prio(p) -> str:
    """The PR's priority: its own priority:Pn label, else the best one of the issues it closes; "none" if neither."""
    own = [l["name"].split(":", 1)[1] for l in p["labels"] if l["name"].startswith("priority:")]
    linked = [ISSUE_PRIO.get(c.get("number"), "") for c in (p.get("closingIssuesReferences") or [])]
    found = [x for x in own + linked if x in PRIOS]
    return min(found, key=PRIOS.index) if found else "none"


merged = gh("pr", "list", "-R", R, "--state", "merged", "--limit", "15", "--json", "number,title,author,mergedAt,url")

COLS = [("ready", "Ready to merge", "green"), ("approved", "Approved", "teal"), ("review", "Waiting for review", "blue"),
        ("changes", "Needs changes", "red"), ("conflicts", "Conflicts", "orange"), ("draft", "Draft / in progress", "grey")]
cols = {k: [] for k, _, _ in COLS}
for p in prs:
    L = {l["name"] for l in p["labels"]}
    if "ready to merge" in L:
        k = "ready"
    elif "needs changes" in L or p.get("reviewDecision") == "CHANGES_REQUESTED":
        k = "changes"
    elif p.get("mergeable") == "CONFLICTING":
        k = "conflicts"
    elif p["isDraft"] or "in progress" in L:
        k = "draft"
    elif p.get("reviewDecision") == "APPROVED":
        k = "approved"
    else:
        k = "review"
    cols[k].append(p)


def card(p):
    L = [l["name"] for l in p["labels"]]
    pr_p = pr_prio(p)
    pills = [f'<span class="pill {"red" if pr_p in ("P0", "P1") else ("orange" if pr_p == "P2" else "grey")}">{pr_p}</span>'] if pr_p != "none" else []
    pills += [f'<span class="pill grey">{esc(x[5:])}</span>' for x in L if x.startswith("area:")]
    if p.get("mergeable") == "CONFLICTING":
        pills.append('<span class="pill orange">conflicting</span>')
    if p["baseRefName"] not in ("main", "master"):
        pills.append(f'<span class="pill grey">into {esc(p["baseRefName"])}</span>')
    old = "old" if days_since(p["updatedAt"]) > 14 else ""
    who = p["author"]["login"]
    return (f'<a class="card {old}" data-p="{pr_p}" data-who="{esc(who.lower())}" data-t="{esc(("#" + str(p["number"]) + " " + p["title"]).lower())}" href="{esc(p["url"])}">'
            f'<div class="num">#{p["number"]:,} <span class="who">{esc(who)} · {ago(p["updatedAt"])} ago</span></div>'
            f'<div class="t">{esc(p["title"])}</div><div class="pills">{"".join(pills)}</div></a>')


board = "".join(
    f'<section class="col"><h2><span class="dot {c}"></span>{esc(n)} <span class="n" data-col="{k}">{len(cols[k]):,}</span></h2>'
    + "".join(card(p) for p in sorted(cols[k], key=lambda p: p["updatedAt"], reverse=True)) + "</section>" for k, n, c in COLS)
mrows = "".join(f'<tr><td><a href="{esc(m["url"])}">#{m["number"]:,}</a> {esc(m["title"])}</td><td>{esc(m["author"]["login"])}</td>'
                f'<td>{ago(m["mergedAt"])} ago</td></tr>' for m in merged)
active = sum(1 for p in prs if days_since(p["updatedAt"]) <= 14)
now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

nowiso = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>SolidCraft PR status</title><style>.fp{{display:inline-flex;align-items:center;gap:4px;font-size:13px;cursor:pointer}}.gh{{display:inline-flex;align-items:center;color:var(--mut);text-decoration:none;padding:4px}}.gh:hover{{color:var(--fg)}}.gh svg{{width:20px;height:20px;fill:currentColor}}.ar{{display:inline-flex;gap:5px;align-items:center;cursor:pointer;color:var(--mut);position:relative;outline:none}}.ar:hover::after,.ar:focus::after{{content:attr(data-tip);position:absolute;top:2em;left:0;z-index:20;width:280px;white-space:normal;font-size:12px;line-height:1.35;padding:7px 9px;border-radius:8px;background:var(--fg);color:var(--bg);box-shadow:0 4px 14px rgba(0,0,0,.25)}}
:root{{color-scheme:light dark;--bg:#f6f7f9;--card:#fff;--fg:#1d2228;--mut:#667;--line:#e2e5ea;
--green:#1f9d55;--teal:#0f8b8d;--blue:#2f6fde;--red:#d64545;--orange:#e07b14;--grey:#8a94a3}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111418;--card:#1b2026;--fg:#e6e9ee;--mut:#9aa3ad;--line:#2a3038}}}}
*{{box-sizing:border-box}}body{{margin:0;font:14px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--bg);color:var(--fg)}}
header{{padding:16px;display:flex;flex-wrap:wrap;gap:10px;align-items:center;border-bottom:1px solid var(--line)}}
h1{{font-size:18px;margin:0 12px 0 0}}.upd{{color:var(--mut);margin-left:auto}}
.btn,button,input{{padding:6px 10px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--fg);font:inherit;text-decoration:none}}
button.on{{border-color:var(--blue);color:var(--blue)}}
.board{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px;padding:16px}}
.col h2{{font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut);margin:0 0 8px;display:flex;align-items:center;gap:6px}}
.n{{background:var(--line);border-radius:10px;padding:0 7px;color:var(--fg)}}.dot{{width:9px;height:9px;border-radius:50%;display:inline-block}}
.card{{display:block;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:9px 10px;margin-bottom:8px;text-decoration:none;color:var(--fg)}}
.card:hover{{border-color:var(--blue)}}.num{{font-weight:600}}.who{{font-weight:400;color:var(--mut);font-size:12px}}.t{{margin:3px 0 6px}}
.pills{{display:flex;flex-wrap:wrap;gap:4px}}.pill{{font-size:11px;padding:1px 7px;border-radius:9px;color:#fff}}
.green{{background:var(--green)}}.teal{{background:var(--teal)}}.blue{{background:var(--blue)}}.red{{background:var(--red)}}.orange{{background:var(--orange)}}.grey{{background:var(--grey)}}
body.recent .card.old{{display:none}}.hide{{display:none!important}}
.wrap{{padding:0 16px 24px}}table{{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line)}}
td{{padding:6px 8px;border-top:1px solid var(--line)}}a{{color:var(--blue)}}h3{{font-size:13px;color:var(--mut);margin:8px 0}}
</style></head><body class="recent">
<header><h1>SolidCraft PRs</h1><label class="ar" tabindex="0" data-tip="Reloads this page every minute to show the latest published copy. It does not fetch new data from GitHub: the page itself is rebuilt on the server every 15 minutes."><input type="checkbox" id="ar"> Auto refresh</label><a class="btn" href="stats.html">Stats</a><a class="btn" href="https://tangency-labs.github.io/leaderboard/">Leaderboard</a>
<button id="b14" class="on">Active 14 days ({active:,})</button><button id="ball">All open ({len(prs):,})</button>
<input id="q" placeholder="Filter: PR #, author or title" size="26"><label class="fp"><input type="checkbox" value="P0">P0</label><label class="fp"><input type="checkbox" value="P1">P1</label><label class="fp"><input type="checkbox" value="P2">P2</label><label class="fp"><input type="checkbox" value="P3">P3</label><label class="fp"><input type="checkbox" value="none">none</label><button id="fclear" type="button">Clear</button>
<span class="upd">updated {now}<span class="ago" data-ts="{nowiso}"></span> · every 15 min</span><a class="gh" href="https://github.com/mkinney/craftydevs-dashboards" title="Source of these pages on GitHub" aria-label="Source of these pages on GitHub"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg></a></header>
<div class="board">{board}</div>
<div class="wrap"><h3>Recently merged</h3><table>{mrows}</table></div>
<script>
const b=document.body,q=document.getElementById('q');
const boxes=[...document.querySelectorAll('.fp input')],K='sc-board-filter';
try{{const d=JSON.parse(localStorage.getItem(K)||'{{}}');if(d.q)q.value=d.q;(d.p||[]).forEach(v=>boxes.forEach(b=>{{if(b.value==v)b.checked=true}}))}}catch(e){{}}
const u=new URLSearchParams(location.search);if(u.get('q')!==null)q.value=u.get('q');if(u.get('p')){{const ps=u.get('p').split(',');boxes.forEach(b=>b.checked=ps.includes(b.value))}}
boxes.forEach(b=>b.onchange=()=>apply());document.getElementById('fclear').onclick=()=>{{q.value='';boxes.forEach(b=>b.checked=false);apply()}};
function apply(){{const v=q.value.trim().toLowerCase(),ps=boxes.filter(b=>b.checked).map(b=>b.value);try{{localStorage.setItem(K,JSON.stringify({{q:q.value,p:ps}}))}}catch(e){{}}
document.querySelectorAll('.card').forEach(c=>{{c.classList.toggle('hide',(!!v&&!(c.dataset.who.includes(v)||c.dataset.t.includes(v)))||(ps.length>0&&!ps.includes(c.dataset.p)))}});
document.querySelectorAll('.col').forEach(col=>{{const n=[...col.querySelectorAll('.card')].filter(c=>getComputedStyle(c).display!=='none').length;col.querySelector('.n').textContent=n.toLocaleString()}});}}
document.getElementById('b14').onclick=()=>{{b.classList.add('recent');b14.classList.add('on');ball.classList.remove('on');apply()}};
document.getElementById('ball').onclick=()=>{{b.classList.remove('recent');ball.classList.add('on');b14.classList.remove('on');apply()}};
q.oninput=apply;apply();
</script><script>(function(){{function t(){{document.querySelectorAll(".ago").forEach(function(e){{var m=Math.max(0,Math.round((Date.now()-Date.parse(e.dataset.ts))/60000));e.textContent=" · "+(m<1?"just now":m<60?m+" minute"+(m==1?"":"s")+" ago":Math.floor(m/60)+" h "+(m%60)+" min ago");}});}}t();setInterval(t,30000);}})();</script><script>(function(){{var k="autoRefresh",b=document.getElementById("ar"),t=null;function on(){{try{{return localStorage.getItem(k)!=="0"}}catch(e){{return true}}}}function set(v){{try{{localStorage.setItem(k,v?"1":"0")}}catch(e){{}}}}function arm(){{clearInterval(t);if(b.checked)t=setInterval(function(){{location.reload()}},60000)}}b.checked=on();arm();b.onchange=function(){{set(b.checked);arm()}};}})();</script></body></html>"""
os.makedirs(os.path.dirname(OUT), exist_ok=True)
open(OUT + ".tmp", "w").write(page)
os.replace(OUT + ".tmp", OUT)
sys.exit(publish(OUT, DEST))
