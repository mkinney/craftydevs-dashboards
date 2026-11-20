#!/usr/bin/env python3
"""Compute and AI-subscription status page (aggregate only).

Public-page rule: no host names, IP addresses, account names or emails - only counts, percentages and generic labels.
Inputs (COMPUTE_DATA, default ~/m5data): perf/<host>.tsv (ts load cpus cpu% mem% diskGB top, every 5 min) and
subs.tsv (utc, then the weekly-use columns read below). COMPUTE_HOSTS: space-separated host names to count (required;
kept out of this file). COMPUTE_OUT: the page to write. Publishing (rsync) is left to the caller.

Buckets (3, like an uptime page):
  compute, per machine, by its average CPU over the last hour: Busy >= 60 %, Working 15-60 %, Idle < 15 %.
  subscriptions, by weekly use: OK, Tight (>= 80 % used), Out (>= 97 % used).
"""
import datetime as dt, html, os, statistics, sys

D = os.path.expanduser(os.environ.get("COMPUTE_DATA", "~/m5data"))   # perf/<host>.tsv and subs.tsv
POOL = os.environ.get("COMPUTE_HOSTS", "").split()   # CamCraft compute only (names stay private: never printed)
if not POOL:
    sys.exit("set COMPUTE_HOSTS (space-separated host names) - they are kept out of the source")
NOW = dt.datetime.now(dt.timezone.utc)


def ts(s):
    return dt.datetime.strptime(s.rstrip("Z")[:19], "%Y-%m-%dT%H:%M:%S" if len(s) > 17 else "%Y-%m-%dT%H:%M").replace(tzinfo=dt.timezone.utc)


def hour_cpu(host):
    p = os.path.join(D, "perf", f"{host}.tsv")
    if not os.path.exists(p):
        return None, None
    vals, cpus, day = [], None, []
    for line in open(p, errors="ignore"):
        f = line.rstrip("\n").split("\t")
        if len(f) < 4:
            continue
        try:
            t, c, u = ts(f[0]), int(f[2]), float(f[3])
        except ValueError:
            continue
        age = (NOW - t).total_seconds()
        if age <= 3600:
            vals.append(u); cpus = c
        if age <= 86400:
            day.append(u)
    if not vals:
        return None, cpus
    return (statistics.mean(vals), statistics.mean(day) if day else None), cpus


def bucket_cpu(u):
    return "busy" if u >= 60 else "working" if u >= 15 else "idle"


rows, cores, day_avgs = {"busy": 0, "working": 0, "idle": 0, "offline": 0}, 0, []
for h in POOL:
    v, c = hour_cpu(h)
    if v is None:
        rows["offline"] += 1; continue
    rows[bucket_cpu(v[0])] += 1; cores += c or 0
    if v[1] is not None:
        day_avgs.append(v[1])

subs_rows = [l.rstrip("\n").split("\t") for l in open(os.path.join(D, "subs.tsv"), errors="ignore") if l[:2] == "20"]
last = subs_rows[-1] if subs_rows else []


def num(i):
    try:
        return float(last[i])
    except (IndexError, ValueError):
        return None


# subs.tsv columns: utc, then weekly use % of: personal plan, team seat 1, (session), team seat 2, (session), codex, gemini-left
subs = [("Claude, personal plan", num(1)), ("Claude Team seat 1", num(2)), ("Claude Team seat 2", num(4)),
        ("Codex (ChatGPT Pro)", num(6)),
        ("Gemini (Antigravity)", None if num(7) is None else 100 - num(7))]


def bucket_sub(used):
    if used is None:
        return "unknown"
    if used >= 97:
        return "out"
    return "tight" if used >= 80 else "ok"


COL = {"busy": "#2f6fde", "working": "#1f9d55", "idle": "#98a2b3", "offline": "#d64545",
       "ok": "#1f9d55", "tight": "#d98a00", "out": "#d64545", "unknown": "#98a2b3"}
LBL = {"busy": "Busy", "working": "Working", "idle": "Idle", "offline": "Offline",
       "ok": "OK", "tight": "Tight", "out": "Out", "unknown": "No data"}

machines = sum(rows.values())
cards = "".join(
    f'<div class="b"><span class="dot" style="background:{COL[k]}"></span><b>{rows[k]}</b><span>{LBL[k]}</span></div>'
    for k in ("busy", "working", "idle", "offline"))
sub_html = ""
for name, used in subs:
    b = bucket_sub(used)
    pct = "-" if used is None else f"{used:.0f}% of the week used"
    w = 0 if used is None else max(0, min(100, used))
    sub_html += (f'<div class="s"><div class="sn"><span class="dot" style="background:{COL[b]}"></span>{html.escape(name)}'
                 f'<span class="tag" style="color:{COL[b]}">{LBL[b]}</span></div>'
                 f'<div class="bar"><i style="width:{w:.0f}%;background:{COL[b]}"></i></div><div class="mut">{pct}</div></div>')
day = f"{statistics.mean(day_avgs):.0f}%" if day_avgs else "-"
updated = NOW.strftime("%Y-%m-%d %H:%M UTC")

page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><script>try{{var t=localStorage.getItem("theme");if(t==="light"||t==="dark")document.documentElement.setAttribute("data-theme",t)}}catch(e){{}}</script><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CamCraft compute</title><meta http-equiv="refresh" content="300"><style>
:root{{--bg:#f6f7f9;--card:#fff;--fg:#1d2330;--mut:#667085;--line:#e3e6eb}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#0f1218;--card:#171b23;--fg:#e6e9ef;--mut:#98a2b3;--line:#2a303b}}}}
:root[data-theme=dark]{{--bg:#0f1218;--card:#171b23;--fg:#e6e9ef;--mut:#98a2b3;--line:#2a303b}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:760px;margin:0 auto;padding:24px 16px}} h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;margin:28px 0 10px}}
.mut{{color:var(--mut);font-size:13px}} .card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px}}
.b{{display:flex;align-items:center;gap:8px}} .b b{{font-size:22px}} .dot{{width:10px;height:10px;border-radius:50%;display:inline-block;flex:none}}
.s{{margin:12px 0}} .sn{{display:flex;align-items:center;gap:8px;font-weight:600}} .tag{{margin-left:auto;font-size:13px}}
.bar{{height:8px;background:var(--line);border-radius:4px;overflow:hidden;margin:6px 0 2px}} .bar i{{display:block;height:100%}}
:root[data-theme=light]{{color-scheme:light}}:root[data-theme=dark]{{color-scheme:dark}}.theme{{display:inline-flex;flex:0 0 auto;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:var(--card)}}.theme button{{margin:0;padding:3px 9px;border:0;border-radius:0;background:transparent;color:var(--mut);font:inherit;font-size:12px;cursor:pointer}}.theme button+button{{border-left:1px solid var(--line)}}.theme button:hover{{color:var(--fg)}}.theme button[aria-pressed=true]{{background:var(--fg);color:var(--bg)}}.theme.r{{margin-left:auto}}
</style></head><body><main>
<header style="display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;margin-bottom:8px"><nav class="mut"><a href="./">CamCraft PRs</a> · <a href="issues.html">Issues</a> · <a href="stats.html">Stats</a> · <a href="/">craftydevs.org</a></nav><span class="theme r" role="group" aria-label="Colour theme" data-theme-switch><button type="button" data-t="light" aria-pressed="false">Light</button><button type="button" data-t="auto" aria-pressed="true">Auto</button><button type="button" data-t="dark" aria-pressed="false">Dark</button></span></header><h1>CamCraft compute</h1><div class="mut">The machines and AI subscriptions that build, test and review CamCraft. Updated {updated}; refreshes every 5 minutes.</div>
<h2>Machines ({machines}, {cores} CPU cores online)</h2>
<div class="card"><div class="grid">{cards}</div>
<div class="mut" style="margin-top:12px">Per machine, average CPU over the last hour: Busy 60% or more, Working 15-60%, Idle under 15%. Average over 24 hours: {day}.</div></div>
<h2>AI subscriptions</h2><div class="card">{sub_html}
<div class="mut">OK: on pace for the week. Tight: 80% or more of the weekly limit used. Out: the weekly limit is reached until its reset.</div></div>
</main><script>(function(){{var r=document.documentElement,bs=[].slice.call(document.querySelectorAll(".theme button"));function cur(){{var v=r.getAttribute("data-theme");return v==="light"||v==="dark"?v:"auto"}}function show(){{var c=cur();bs.forEach(function(b){{b.setAttribute("aria-pressed",b.getAttribute("data-t")===c?"true":"false")}})}}bs.forEach(function(b){{b.addEventListener("click",function(){{var v=b.getAttribute("data-t");if(v==="auto"){{r.removeAttribute("data-theme");try{{localStorage.removeItem("theme")}}catch(e){{}}}}else{{r.setAttribute("data-theme",v);try{{localStorage.setItem("theme",v)}}catch(e){{}}}}show()}})}});show()}})();</script></body></html>"""
out = os.path.expanduser(os.environ.get("COMPUTE_OUT", os.path.join(D, "compute.html")))
with open(out + ".tmp", "w") as f:
    f.write(page)
os.replace(out + ".tmp", out)
print(f"wrote {out}: machines {rows}, cores {cores}, subs {[(n, bucket_sub(u)) for n, u in subs]}")
