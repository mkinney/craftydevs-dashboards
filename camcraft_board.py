#!/usr/bin/env python3
"""CamCraft PR dashboard: one static, public page built from `gh` only (no AI).
Runs every minute from cron and publishes to https://craftydevs.org/camcraft/status/ (user, 2026-11-16).
Style inspired by merge-queue dashboards (queue list, status pills, cards); the design and code are our own."""
import datetime as dt, html, json, os, subprocess, sys

R = "NeoTech/Camcraft"
GH = next((p for p in ("/opt/homebrew/bin/gh", "/usr/local/bin/gh", "gh") if p == "gh" or os.path.exists(p)), "gh")
OUT = os.path.expanduser(os.environ.get("CAMCRAFT_BOARD_OUT", "~/dashboards/camcraft/index.html"))
DEST = os.environ.get("CAMCRAFT_BOARD_DEST", "")



def publish(path: str, dest: str) -> int:
    """Copy the page to DEST (an rsync target such as user@host:public_html/status/index.html); no DEST = keep local."""
    if not dest:
        print(f"wrote {path} (set the DEST variable to publish it)")
        return 0
    return subprocess.run(["rsync", "-q", "-e", "ssh -o BatchMode=yes", path, dest], capture_output=True, text=True,
                          timeout=60).returncode

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


def esc(s):
    return html.escape(str(s or ""))


prs = gh("pr", "list", "-R", R, "--state", "open", "--limit", "300", "--json",
         "number,title,author,isDraft,labels,mergeable,headRefOid,createdAt,updatedAt,reviews,comments,url,baseRefName,statusCheckRollup")
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


def card(p):
    L = labels(p)
    t = p["title"]
    feat = kind(t) == "feat"
    pills = []
    if feat:
        pills.append('<span class="pill grey">feat · at cut</span>')
    if "P1" in L or "P2" in L:
        pills.append('<span class="pill red">P1/P2</span>')
    if p.get("mergeable") == "CONFLICTING":
        pills.append('<span class="pill orange">conflicting</span>')
    if reviewed(p):
        pills.append('<span class="pill green">reviewed head</span>')
    elif not p["isDraft"]:
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
    return (f'<a class="card" href="{esc(p["url"])}"><div class="num">#{p["number"]} '
            f'<span class="who">{esc(p["author"]["login"])} · {ago(p["updatedAt"])} ago</span></div>'
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
    t = ST.get("train") or {}
    if t:
        res = t.get("result", "")
        icon = {"GREEN": "🟢", "RED": "🔴"}.get(res, "⚪")
        prs_ = " ".join("#" + x for x in t.get("in", []))
        out.append(f'<span class="main {"ok" if res == "GREEN" else ("bad" if res == "RED" else "run")}">last batch test: <b>{icon} {esc(res.lower())}</b> · {esc(prs_)} · {ago(t.get("time"))} ago</span>')
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
    return (f'<tr><td><span class="pill {"red" if pr in ("P1","P2") else "orange"}">{pr}</span></td>'
            f'<td><a href="{esc(b["url"])}">#{b["number"]}</a> {esc(b["title"])}</td><td>{st}</td></tr>')

bugs_html = "".join(bug_row(b) for b in sorted(bugs, key=lambda b: ([l["name"] for l in b["labels"] if l["name"] in ("P1","P2","P3")] or ["P9"])[0]))
merged_html = "".join(f'<tr><td><a href="{esc(m["url"])}">#{m["number"]}</a> {esc(m["title"])}</td>'
                      f'<td>{esc(m["author"]["login"])}</td><td>{ago(m["mergedAt"])} ago</td></tr>' for m in merged)

nowiso = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CamCraft PR status</title><style>.ar{{display:inline-flex;gap:5px;align-items:center;cursor:pointer;color:var(--mut);position:relative;outline:none}}.ar:hover::after,.ar:focus::after{{content:attr(data-tip);position:absolute;top:2em;left:0;z-index:20;width:280px;white-space:normal;font-size:12px;line-height:1.35;padding:7px 9px;border-radius:8px;background:var(--fg);color:var(--bg);box-shadow:0 4px 14px rgba(0,0,0,.25)}}
:root{{color-scheme:light dark;--bg:#f6f7f9;--card:#fff;--fg:#1d2228;--mut:#667;--line:#e2e5ea;
--green:#1f9d55;--blue:#2f6fde;--red:#d64545;--orange:#e07b14;--yellow:#c9a400;--grey:#8a94a3}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111418;--card:#1b2026;--fg:#e6e9ee;--mut:#9aa3ad;--line:#2a3038}}}}
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
</style></head><body>
<header><h1>CamCraft PRs</h1><label class="ar" tabindex="0" data-tip="Reloads this page every minute to show the latest published copy. It does not fetch new data from GitHub: the page itself is rebuilt on the server every minute."><input type="checkbox" id="ar"> Auto refresh</label><a class="main" href="stats.html">Stats</a>{main_html}{rel_html}{strip()}<span class="upd">{len(prs)} open · updated {now}<span class="ago" data-ts="{nowiso}"></span></span></header>
<div class="board">{board}</div>
<div class="wrap"><div><h3>Open P1–P3 bugs ({len(bugs)})</h3><table>{bugs_html}</table></div>
<div><h3>Recently merged</h3><table>{merged_html}</table></div></div>
<script>(function(){{function t(){{document.querySelectorAll(".ago").forEach(function(e){{var m=Math.max(0,Math.round((Date.now()-Date.parse(e.dataset.ts))/60000));e.textContent=" · "+(m<1?"just now":m<60?m+" minute"+(m==1?"":"s")+" ago":Math.floor(m/60)+" h "+(m%60)+" min ago");}});}}t();setInterval(t,30000);}})();</script><script>(function(){{var k="autoRefresh",b=document.getElementById("ar"),t=null;function on(){{try{{return localStorage.getItem(k)!=="0"}}catch(e){{return true}}}}function set(v){{try{{localStorage.setItem(k,v?"1":"0")}}catch(e){{}}}}function arm(){{clearInterval(t);if(b.checked)t=setInterval(function(){{location.reload()}},60000)}}b.checked=on();arm();b.onchange=function(){{set(b.checked);arm()}};}})();</script></body></html>"""

os.makedirs(os.path.dirname(OUT), exist_ok=True)
tmp = OUT + ".tmp"
open(tmp, "w").write(page)
os.replace(tmp, OUT)
sys.exit(publish(OUT, DEST))
