#!/usr/bin/env python3
"""CamCraft PR dashboard: one static, public page built from `gh` only (no AI).
Runs every minute from cron and publishes to https://craftydevs.org/camcraft/status/ (user, 2026-11-16).
Style inspired by merge-queue dashboards (queue list, status pills, cards); the design and code are our own."""
import datetime as dt, html, json, os, subprocess, sys

R = "NeoTech/Camcraft"
GH = next((p for p in ("/opt/homebrew/bin/gh", "/usr/local/bin/gh", "gh") if p == "gh" or os.path.exists(p)), "gh")
OUT = os.path.expanduser(os.environ.get("CAMCRAFT_BOARD_OUT", "~/dashboards/camcraft/index.html"))
DEST = os.environ.get("CAMCRAFT_BOARD_DEST", "")


def gh(*args):
    r = subprocess.run([GH, *args], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:300])
    return json.loads(r.stdout) if r.stdout.strip() else []


def ago(ts):
    if not ts:
        return ""
    t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    s = (dt.datetime.now(dt.timezone.utc) - t).total_seconds()
    if s < 3600:
        return f"{int(s // 60)}m"
    if s < 86400:
        return f"{int(s // 3600)}h"
    return f"{int(s // 86400)}d"


def publish(path: str, dest: str) -> int:
    """Copy the page to DEST (an rsync target such as user@host:public_html/status/index.html); no DEST = keep local."""
    if not dest:
        print(f"wrote {path} (set the DEST variable to publish it)")
        return 0
    return subprocess.run(["rsync", "-q", "-e", "ssh -o BatchMode=yes", path, dest], capture_output=True, text=True,
                          timeout=60).returncode

def esc(s):
    return html.escape(str(s or ""))


prs = gh("pr", "list", "-R", R, "--state", "open", "--limit", "300", "--json",
         "number,title,author,isDraft,labels,mergeable,headRefOid,createdAt,updatedAt,reviews,comments,url,baseRefName,statusCheckRollup,closingIssuesReferences,files")
PRIOS = ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P?"]
try:
    _iss = gh("issue", "list", "-R", R, "--state", "all", "--limit", "1500", "--search", "sort:updated-desc",
              "--json", "number,labels")
except Exception:
    _iss = []
ISSUE_PRIO = {i["number"]: next((l["name"] for l in i["labels"] if l["name"] in PRIOS), "") for i in _iss}


def pr_prio(p) -> str:
    """The PR's priority: its own P label, else the best P label of the issues it closes; "none" if neither."""
    own = [l["name"] for l in p.get("labels", []) if l["name"] in PRIOS]
    linked = [ISSUE_PRIO.get(c.get("number"), "") for c in (p.get("closingIssuesReferences") or [])]
    found = [x for x in own + linked if x]
    return min(found, key=PRIOS.index) if found else "none"


merged = gh("pr", "list", "-R", R, "--state", "merged", "--limit", "15", "--json", "number,title,author,mergedAt,url")
bugs = gh("issue", "list", "-R", R, "--state", "open", "--limit", "100", "--search", "label:P1,P2,P3",
          "--json", "number,title,labels,assignees,url,updatedAt")
try:
    runs = gh("run", "list", "-R", R, "--workflow", "post-merge.yml", "--limit", "1",
              "--json", "conclusion,status,headSha,url,createdAt")
except Exception:
    runs = []
try:
    rel = gh("pr", "list", "-R", R, "--state", "open", "--search", "head:release/", "--json", "number,title,url")
except Exception:
    rel = []


try:
    ST = json.load(open(os.path.expanduser(os.environ.get("DASH_STATUS", "~/dashboards/status.json"))))
except Exception:
    ST = {}
ACT = ST.get("pr_activity", {})


def labels(p):
    return [l["name"] for l in p.get("labels", [])]


def reviewed(p):
    m = "pr-reviewer: " + p["headRefOid"]
    return any(m in (x.get("body") or "") for x in p.get("reviews", []) + p.get("comments", []))


COLS = [
    ("ready", "Merge-ready", "green"),
    ("review", "In review", "blue"),
    ("rework", "Needs rework", "red"),
    ("conflicts", "Conflicts", "orange"),
    ("maint", "Waiting on maintainer", "yellow"),
    ("draft", "Draft / in progress", "grey"),
]
cols = {k: [] for k, _, _ in COLS}
for p in prs:
    L = labels(p)
    if p["isDraft"] and "needs-rework" not in L and "conflicts" not in L:
        k = "draft"
    elif "needs-maintainer" in L:
        k = "maint"
    elif "needs-rework" in L:
        k = "rework"
    elif "conflicts" in L or p.get("mergeable") == "CONFLICTING":
        k = "conflicts"
    elif "merge-ready" in L:
        k = "ready"
    else:
        k = "review"
    cols[k].append(p)

kind = lambda t: (t.split("(")[0].split(":")[0].rstrip("!") or "?")


def maint_why(p):
    """Short reason a needs-maintainer PR waits, from the files it changes."""
    fs = [f.get("path", "") for f in p.get("files") or []]
    why = []
    if any(f in ("Cargo.toml", "Cargo.lock") or f.endswith("/Cargo.toml") for f in fs):
        why.append("dependencies")
    if any(f.startswith((".github/", "scripts/", "aur/")) or f.endswith("build.rs") for f in fs):
        why.append("build/scripts")
    return " + ".join(dict.fromkeys(why)) or "design call"


def card(p):
    L = labels(p)
    t = p["title"]
    feat = kind(t) == "feat"
    pills = []
    if feat:
        pills.append('<span class="pill grey" title="merges when clean, after the post-merge runs (Sarge OK 2026-11-20)">feat</span>')
    if p.get("mergeable") == "CONFLICTING":
        pills.append('<span class="pill orange">conflicting</span>')
    if "needs-maintainer" in L:
        why = maint_why(p)
        pills.append(f'<span class="pill yellow" title="The maintainer decides before a review or merge (needs-maintainer)">maintainer decision: {esc(why)}</span>')
    if reviewed(p):
        pills.append('<span class="pill green">reviewed head</span>')
    elif not p["isDraft"] and "needs-maintainer" not in L:
        pills.append('<span class="pill blue">review pending</span>')
    # agent/* commit statuses: the shared "someone is working on this" sign (both coordinators can set them)
    for st in p.get("statusCheckRollup") or []:
        ctx = st.get("context") or ""
        if ctx.startswith("agent/"):
            stt = (st.get("state") or "").upper()
            cls = {"PENDING": "yellow", "SUCCESS": "green", "FAILURE": "red", "ERROR": "red"}.get(stt, "grey")
            ic = {"PENDING": "⏳", "SUCCESS": "✅", "FAILURE": "❌", "ERROR": "❌"}.get(stt, "•")
            parts = ctx[6:].split("/")               # agent/<kind>[/<who>]
            who = f" · {parts[1]}" if len(parts) > 1 else ""
            since = f" · {ago(st['startedAt'])}" if st.get("startedAt") and stt == "PENDING" else ""
            pills.append(f'<span class="pill {cls}">{ic} {esc(parts[0])}{esc(who)}{esc(since)}</span>')
    a = ACT.get(str(p["number"]))
    if a:
        icon = {"fixup": "🔧", "mergefix": "🔀", "review": "🔍", "work": "🛠"}.get(a.split()[-1] if a.startswith("queued") else a.split()[0], "⚙")
        pills.append(f'<span class="pill act">{icon} {esc(a)}</span>')
    if p["baseRefName"] != "main":
        pills.append(f'<span class="pill grey">stacked on {esc(p["baseRefName"])}</span>')
    pr_p = pr_prio(p)
    if pr_p != "none":
        pills.insert(0, f'<span class="pill {"red" if pr_p in ("P1", "P2") else ("orange" if pr_p == "P3" else "grey")}">{pr_p}</span>')
    return (f'<a class="card" data-p="{esc(pr_p)}" data-k="{esc(("#" + str(p["number"]) + " " + p["author"]["login"] + " " + t).lower())}" '
            f'href="{esc(p["url"])}"><div class="num">#{p["number"]} '
            f'<span class="who">{esc(p["author"]["login"])} · opened {ago(p["createdAt"])} ago · updated {ago(p["updatedAt"])} ago</span></div>'
            f'<div class="t">{esc(t)}</div><div class="pills">{"".join(pills)}</div></a>')


now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
if runs:
    r0 = runs[0]
    state = r0.get("conclusion") or r0.get("status")
    good = state == "success"
    main_html = (f'<a class="main {"ok" if good else ("bad" if state in ("failure", "cancelled") else "run")}" href="{esc(r0["url"])}">'
                 f'main <b>{esc(r0["headSha"][:9])}</b> · post-merge gate: <b>{esc(state)}</b> · {ago(r0["createdAt"])} ago</a>')
else:
    main_html = '<span class="main run">main · post-merge gate: unknown</span>'
def strip():
    out = []
    h = ST.get("main_health") or {}
    if h:
        ok = h.get("state") == "GREEN"
        out.append(f'<span class="main {"ok" if ok else "bad"}">main build check: <b>{"🟢 green" if ok else "🔴 red"}</b> on {esc(h.get("sha"))} · {ago(h.get("time"))} ago</span>')
    if ST:
        d = ST.get("done_today", {})
        parts = " · ".join(f"{v} {k}{'s' if v != 1 else ''}" for k, v in sorted(d.items(), key=lambda kv: -kv[1]))
        out.append(f'<span class="main">workers <b>{ST.get("busy", 0)} busy / {ST.get("slots", 0)}</b> · queue {ST.get("queued", 0)} · done today: {esc(parts) or "none"}</span>')
    return "".join(out)


rel_html = "".join(f'<a class="main run" href="{esc(x["url"])}">release in progress: #{x["number"]} {esc(x["title"])}</a>' for x in rel)

board = "".join(
    f'<section class="col"><h2><span class="dot {c}"></span>{esc(name)} <span class="n">{len(cols[k])}</span></h2>'
    + "".join(card(p) for p in sorted(cols[k], key=lambda p: p["number"]))
    + "</section>" for k, name, c in COLS)

def bug_row(b):
    L = [l["name"] for l in b["labels"]]
    pr = next((x for x in L if x in ("P1", "P2", "P3")), "")
    st = "in review" if "in-review" in L else ("claimed" if "claimed" in L else ("blocked" if "blocked" in L else "open"))
    return (f'<tr class="bug" data-p="{pr}" data-k="{esc(("#" + str(b["number"]) + " " + " ".join(a["login"] for a in b.get("assignees", [])) + " " + b["title"]).lower())}">'
            f'<td><span class="pill {"red" if pr in ("P1","P2") else "orange"}">{pr}</span></td>'
            f'<td><a href="{esc(b["url"])}">#{b["number"]}</a> {esc(b["title"])}</td><td>{st}</td></tr>')

bugs_html = "".join(bug_row(b) for b in sorted(bugs, key=lambda b: ([l["name"] for l in b["labels"] if l["name"] in ("P1","P2","P3")] or ["P9"])[0]))
merged_html = "".join(f'<tr><td><a href="{esc(m["url"])}">#{m["number"]}</a> {esc(m["title"])}</td>'
                      f'<td>{esc(m["author"]["login"])}</td><td>{ago(m["mergedAt"])} ago</td></tr>' for m in merged)

nowiso = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><script>try{{var t=localStorage.getItem("theme");if(t==="light"||t==="dark")document.documentElement.setAttribute("data-theme",t)}}catch(e){{}}</script>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CamCraft PR status</title><style>.filters{{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;padding:10px 16px;border-bottom:1px solid var(--line)}}.filters input[type=search]{{padding:6px 10px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--fg);font:inherit;min-width:240px;flex:1 1 240px;max-width:420px}}.fp{{display:inline-flex;align-items:center;gap:4px;font-size:13px;cursor:pointer}}#fclear{{padding:5px 10px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--fg);font:inherit;cursor:pointer}}.hide{{display:none!important}}.gh{{display:inline-flex;align-items:center;color:var(--mut);text-decoration:none;padding:4px}}.gh:hover{{color:var(--fg)}}.gh svg{{width:20px;height:20px;fill:currentColor}}.ar{{display:inline-flex;gap:5px;align-items:center;cursor:pointer;color:var(--mut);position:relative;outline:none}}.ar:hover::after,.ar:focus::after{{content:attr(data-tip);position:absolute;top:2em;left:0;z-index:20;width:280px;white-space:normal;font-size:12px;line-height:1.35;padding:7px 9px;border-radius:8px;background:var(--fg);color:var(--bg);box-shadow:0 4px 14px rgba(0,0,0,.25)}}
:root{{color-scheme:light dark;--bg:#f6f7f9;--card:#fff;--fg:#1d2228;--mut:#667;--line:#e2e5ea;
--green:#1f9d55;--blue:#2f6fde;--red:#d64545;--orange:#e07b14;--yellow:#c9a400;--grey:#8a94a3}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#111418;--card:#1b2026;--fg:#e6e9ee;--mut:#9aa3ad;--line:#2a3038}}}}
:root[data-theme=dark]{{--bg:#111418;--card:#1b2026;--fg:#e6e9ee;--mut:#9aa3ad;--line:#2a3038}}
*{{box-sizing:border-box}}body{{margin:0;font:14px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--bg);color:var(--fg)}}
header{{padding:16px;display:flex;flex-wrap:wrap;gap:10px;align-items:center;border-bottom:1px solid var(--line)}}
h1{{font-size:18px;margin:0 12px 0 0}}.upd{{color:var(--mut);margin-left:auto}}
.main{{padding:6px 10px;border-radius:8px;text-decoration:none;color:var(--fg);border:1px solid var(--line);background:var(--card)}}
.main.ok{{border-color:var(--green)}}.main.bad{{border-color:var(--red);color:var(--red)}}.main.run{{border-color:var(--blue)}}
.board{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px;padding:16px}}
.col h2{{font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut);margin:0 0 8px;display:flex;align-items:center;gap:6px}}
.n{{background:var(--line);border-radius:10px;padding:0 7px;color:var(--fg)}}.dot{{width:9px;height:9px;border-radius:50%;display:inline-block}}
.card{{display:block;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:9px 10px;margin-bottom:8px;text-decoration:none;color:var(--fg)}}
.card:hover{{border-color:var(--blue)}}.num{{font-weight:600}}.who{{font-weight:400;color:var(--mut);font-size:12px}}.t{{margin:3px 0 6px}}
.pills{{display:flex;flex-wrap:wrap;gap:4px}}.pill{{font-size:11px;padding:1px 7px;border-radius:9px;color:#fff}}
.green{{background:var(--green)}}.blue{{background:var(--blue)}}.red{{background:var(--red)}}.orange{{background:var(--orange)}}.yellow{{background:var(--yellow)}}.grey{{background:var(--grey)}}.act{{background:#6b4fd8}}
.wrap{{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:12px;padding:0 16px 24px}}
table{{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}}
td{{padding:6px 8px;border-top:1px solid var(--line);vertical-align:top}}a{{color:var(--blue)}}h3{{font-size:13px;color:var(--mut);margin:8px 0}}
:root[data-theme=light]{{color-scheme:light}}:root[data-theme=dark]{{color-scheme:dark}}.theme{{display:inline-flex;flex:0 0 auto;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:var(--card)}}.theme button{{margin:0;padding:3px 9px;border:0;border-radius:0;background:transparent;color:var(--mut);font:inherit;font-size:12px;cursor:pointer}}.theme button+button{{border-left:1px solid var(--line)}}.theme button:hover{{color:var(--fg)}}.theme button[aria-pressed=true]{{background:var(--fg);color:var(--bg)}}.theme.r{{margin-left:auto}}
</style></head><body>
<header><h1>CamCraft PRs</h1><a href="issues.html">Issues</a><label class="ar" tabindex="0" data-tip="Reloads this page every minute to show the latest published copy. It does not fetch new data from GitHub: the page itself is rebuilt on the server every minute."><input type="checkbox" id="ar"> Auto refresh</label><a class="main" href="stats.html">Stats</a><a class="main" href="compute.html">Compute</a>{main_html}{rel_html}{strip()}<span class="upd">{len(prs)} open · updated {now}<span class="ago" data-ts="{nowiso}"></span></span><a class="gh" href="https://github.com/mkinney/craftydevs-dashboards" title="Source of these pages on GitHub" aria-label="Source of these pages on GitHub"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg></a><span class="theme" role="group" aria-label="Colour theme" data-theme-switch><button type="button" data-t="light" aria-pressed="false">Light</button><button type="button" data-t="auto" aria-pressed="true">Auto</button><button type="button" data-t="dark" aria-pressed="false">Dark</button></span></header><div class="filters"><input id="fq" type="search" placeholder="Filter: PR #, submitter or title" aria-label="Filter PRs"><label class="fp"><input type="checkbox" value="P1">P1</label><label class="fp"><input type="checkbox" value="P2">P2</label><label class="fp"><input type="checkbox" value="P3">P3</label><label class="fp"><input type="checkbox" value="P4">P4</label><label class="fp"><input type="checkbox" value="P5">P5</label><label class="fp"><input type="checkbox" value="P6">P6</label><label class="fp"><input type="checkbox" value="P7">P7</label><label class="fp"><input type="checkbox" value="P8">P8</label><label class="fp"><input type="checkbox" value="P9">P9</label><label class="fp"><input type="checkbox" value="P?">P?</label><label class="fp"><input type="checkbox" value="none">none</label><button id="fclear" type="button">Clear</button><span id="fcount" class="mut"></span></div>
<div class="board">{board}</div>
<div class="wrap"><div><h3>Open P1–P3 bugs ({len(bugs)})</h3><table>{bugs_html}</table></div>
<div><h3>Recently merged</h3><table>{merged_html}</table></div></div>
<script>(function(){{function t(){{document.querySelectorAll(".ago").forEach(function(e){{var m=Math.max(0,Math.round((Date.now()-Date.parse(e.dataset.ts))/60000));e.textContent=" · "+(m<1?"just now":m<60?m+" minute"+(m==1?"":"s")+" ago":Math.floor(m/60)+" h "+(m%60)+" min ago");}});}}t();setInterval(t,30000);}})();</script><script>(function(){{var k="autoRefresh",b=document.getElementById("ar"),t=null;function on(){{try{{return localStorage.getItem(k)!=="0"}}catch(e){{return true}}}}function set(v){{try{{localStorage.setItem(k,v?"1":"0")}}catch(e){{}}}}function arm(){{clearInterval(t);if(b.checked)t=setInterval(function(){{location.reload()}},60000)}}b.checked=on();arm();b.onchange=function(){{set(b.checked);arm()}};}})();</script><script>(function(){{var q=document.getElementById("fq"),boxes=[].slice.call(document.querySelectorAll(".fp input")),cnt=document.getElementById("fcount"),K="cc-board-filter";function save(){{try{{localStorage.setItem(K,JSON.stringify({{q:q.value,p:boxes.filter(function(b){{return b.checked}}).map(function(b){{return b.value}})}}))}}catch(e){{}}}}function load(){{var u=new URLSearchParams(location.search);try{{var d=JSON.parse(localStorage.getItem(K)||"{{}}");if(d.q)q.value=d.q;(d.p||[]).forEach(function(v){{boxes.forEach(function(b){{if(b.value==v)b.checked=true}})}})}}catch(e){{}}if(u.get("q")!==null)q.value=u.get("q");if(u.get("p")){{var ps=u.get("p").split(",");boxes.forEach(function(b){{b.checked=ps.indexOf(b.value)>=0}})}}}}function apply(){{var v=q.value.trim().toLowerCase(),ps=boxes.filter(function(b){{return b.checked}}).map(function(b){{return b.value}}),shown=0,total=0;document.querySelectorAll("[data-k]").forEach(function(e){{var ok=(!v||e.dataset.k.indexOf(v)>=0)&&(!ps.length||ps.indexOf(e.dataset.p)>=0);e.classList.toggle("hide",!ok);if(e.classList.contains("card")){{total++;if(ok)shown++}}}});document.querySelectorAll("section.col").forEach(function(c){{var n=c.querySelector("h2 .n");if(n)n.textContent=c.querySelectorAll(".card:not(.hide)").length}});cnt.textContent=(v||ps.length)?("showing "+shown+" of "+total+" PRs"):"";save()}}q.addEventListener("input",apply);boxes.forEach(function(b){{b.addEventListener("change",apply)}});document.getElementById("fclear").onclick=function(){{q.value="";boxes.forEach(function(b){{b.checked=false}});apply()}};load();apply()}})();</script><script>(function(){{var r=document.documentElement,bs=[].slice.call(document.querySelectorAll(".theme button"));function cur(){{var v=r.getAttribute("data-theme");return v==="light"||v==="dark"?v:"auto"}}function show(){{var c=cur();bs.forEach(function(b){{b.setAttribute("aria-pressed",b.getAttribute("data-t")===c?"true":"false")}})}}bs.forEach(function(b){{b.addEventListener("click",function(){{var v=b.getAttribute("data-t");if(v==="auto"){{r.removeAttribute("data-theme");try{{localStorage.removeItem("theme")}}catch(e){{}}}}else{{r.setAttribute("data-theme",v);try{{localStorage.setItem("theme",v)}}catch(e){{}}}}show()}})}});show()}})();</script></body></html>"""

os.makedirs(os.path.dirname(OUT), exist_ok=True)
os.makedirs(os.path.dirname(OUT), exist_ok=True)
tmp = OUT + ".tmp"
open(tmp, "w").write(page)
os.replace(tmp, OUT)
sys.exit(publish(OUT, DEST))
