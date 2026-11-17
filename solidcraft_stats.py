#!/usr/bin/env python3
"""SolidCraft stats page from GitHub search counts only (no AI), hourly from cron (user, 2026-11-16).
The repo is too large to list (~18,000 items; search returns at most 1,000), so every number is a search `total_count`,
one query per (kind, period). ~110 queries, paced under the 30/min search limit. Publishes /solidcraft/status/stats.html."""
import datetime as dt, html, json, os, subprocess, sys, time, urllib.parse

R = "tangency-labs/solidcraft"
GH = next((p for p in ("/opt/homebrew/bin/gh", "/usr/local/bin/gh") if os.path.exists(p)), "gh")
OUT = os.path.expanduser(os.environ.get("SOLIDCRAFT_STATS_OUT", "~/dashboards/solidcraft/stats.html"))
DEST = os.environ.get("SOLIDCRAFT_STATS_DEST", "")
WEEKS, DAYS = 10, 42
PRIOS = ["P0", "P1", "P2", "P3"]
PDESC = {"P0": "priority:P0 - the most urgent", "P1": "priority:P1 - high", "P2": "priority:P2 - medium", "P3": "priority:P3 - low"}



def publish(path: str, dest: str) -> int:
    """Copy the page to DEST (an rsync target such as user@host:public_html/status/index.html); no DEST = keep local."""
    if not dest:
        print(f"wrote {path} (set the DEST variable to publish it)")
        return 0
    return subprocess.run(["rsync", "-q", "-e", "ssh -o BatchMode=yes", path, dest], capture_output=True, text=True,
                          timeout=60).returncode

def count(q):
    for attempt in range(4):
        r = subprocess.run([GH, "api", "search/issues?per_page=1&q=" + urllib.parse.quote(f"repo:{R} {q}"), "--jq", ".total_count"],
                           capture_output=True, text=True, timeout=60)
        time.sleep(2.3)                       # stay under the 30 searches/minute limit
        if r.returncode == 0 and r.stdout.strip().isdigit():
            return int(r.stdout)
        time.sleep(20)
    return 0


today = dt.datetime.now(dt.timezone.utc).date()
wk = lambda d: d - dt.timedelta(d.weekday())
weeks = [wk(today) - dt.timedelta(7 * w) for w in range(WEEKS - 1, -1, -1)]
rng = lambda a, b: f"{a.isoformat()}..{(b - dt.timedelta(1)).isoformat()}"

W = []
for w in weeks:
    e = min(w + dt.timedelta(7), today + dt.timedelta(1)); r = rng(w, e)
    row = {"w": w, "io": count(f"is:issue created:{r}"), "ic": count(f"is:issue closed:{r}"),
           "po": count(f"is:pr created:{r}"), "pm": count(f"is:pr merged:{r}")}
    for p in PRIOS:
        row["o" + p] = count(f'is:issue created:{r} label:"priority:{p}"')
    W.append(row)
days = [today - dt.timedelta(i) for i in range(DAYS - 1, -1, -1)]
merged = [count(f"is:pr merged:{d.isoformat()}") for d in days]
open_issues = count("is:issue is:open")
open_prs = count("is:pr is:open")
open_prio = {p: count(f'is:issue is:open label:"priority:{p}"') for p in PRIOS}
e = html.escape


def bars(series, labels, colors, h=130):
    n, g = len(labels), len(series); mx = max([1] + [v for _, vs in series for v in vs])
    bw, gap, left, top, bottom = 14, 12, 40, 18, 46
    Wd = left + n * (g * bw + gap) + 10
    o = [f'<svg viewBox="0 0 {Wd} {top + h + bottom}" class="chart" role="img">']
    for k in range(5):
        y = top + h - h * k / 4
        o.append(f'<line x1="{left - 4}" x2="{Wd}" y1="{y:.0f}" y2="{y:.0f}" class="grid"/><text x="{left - 6}" y="{y + 3:.0f}" class="ax" text-anchor="end">{round(mx * k / 4):,}</text>')
    for j, lab in enumerate(labels):
        x0 = left + j * (g * bw + gap)
        for s, (name, vs) in enumerate(series):
            v = vs[j]; bh = h * v / mx; y = top + h - bh
            o.append(f'<g class="b"><rect x="{x0 + s * bw}" y="{y:.1f}" width="{bw - 2}" height="{max(bh, .5):.1f}" fill="{colors[s]}"><title>{e(name)} {e(lab)}: {v:,}</title></rect>'
                     f'<text x="{x0 + s * bw + (bw - 2) / 2:.1f}" y="{y - 3:.1f}" class="val" text-anchor="middle">{v:,}</text></g>')
        cx = x0 + g * bw / 2
        o.append(f'<text x="{cx:.1f}" y="{top + h + 8}" class="ax" text-anchor="end" transform="rotate(-55 {cx:.1f} {top + h + 8})">{e(lab)}</text>')
    o.append("</svg>")
    return "".join(o) + '<div class="legend">' + "".join(f'<span class="lg"><i style="background:{c}"></i>{e(nm)}</span>' for (nm, _), c in zip(series, colors)) + "</div>"


def velocity():
    v = merged; avg = [sum(v[max(0, i - 6):i + 1]) / len(v[max(0, i - 6):i + 1]) for i in range(len(v))]
    Wd, H, L, T, B = 820, 170, 40, 14, 46; mx = max(max(v), 1)
    X = lambda i: L + (Wd - L - 10) * (i / max(1, len(v) - 1)); Y = lambda y: T + H - H * y / mx
    o = [f'<svg viewBox="0 0 {Wd} {T + H + B}" class="chart" role="img">']
    for k in range(5):
        y = T + H - H * k / 4
        o.append(f'<line x1="{L - 4}" x2="{Wd}" y1="{y:.0f}" y2="{y:.0f}" class="grid"/><text x="{L - 6}" y="{y + 3:.0f}" class="ax" text-anchor="end">{round(mx * k / 4):,}</text>')
    pts = lambda a: " ".join(f"{X(i):.1f},{Y(x):.1f}" for i, x in enumerate(a))
    o.append(f'<polyline points="{pts(v)}" fill="none" stroke="#2f6fde" stroke-opacity=".45" stroke-width="1.5"/><polyline points="{pts(avg)}" fill="none" stroke="#1f9d55" stroke-width="3"/>')
    for i, d in enumerate(days):
        o.append(f'<g class="b"><circle cx="{X(i):.1f}" cy="{Y(v[i]):.1f}" r="5" fill="transparent"/><circle cx="{X(i):.1f}" cy="{Y(v[i]):.1f}" r="2" fill="#2f6fde"/>'
                 f'<title>{d}: {v[i]:,} merged · 7-day avg {avg[i]:.1f}</title><text x="{X(i):.1f}" y="{Y(v[i]) - 7:.1f}" class="val" text-anchor="middle">{v[i]:,}</text></g>')
        if i % 3 == 0 or i == len(days) - 1:
            o.append(f'<text x="{X(i):.1f}" y="{T + H + 10}" class="ax" text-anchor="end" transform="rotate(-55 {X(i):.1f} {T + H + 10})">{d.strftime("%m-%d")}</text>')
    o.append("</svg>")
    l7, p7 = sum(v[-7:]), sum(v[-14:-7]); tr = "↑" if l7 > p7 else ("↓" if l7 < p7 else "→")
    return (f'<div class="kpis"><div><b>{l7:,}</b><span>merged, last 7 days {tr} (prior 7: {p7:,})</span></div>'
            f'<div><b>{avg[-1]:.1f}</b><span>per day, 7-day average</span></div><div><b>{open_prs:,}</b><span>open PRs</span></div>'
            f'<div><b>{open_issues:,}</b><span>open issues</span></div></div>' + "".join(o) +
            '<div class="legend"><span class="lg"><i style="background:#2f6fde;opacity:.5"></i>merged per day</span><span class="lg"><i style="background:#1f9d55"></i>7-day average</span></div>')


wl = [x["w"].strftime("%m-%d") for x in W]
issues_w = bars([("opened", [x["io"] for x in W]), ("closed", [x["ic"] for x in W])], wl, ["#2f6fde", "#1f9d55"])
prs_w = bars([("opened", [x["po"] for x in W]), ("merged", [x["pm"] for x in W])], wl, ["#2f6fde", "#1f9d55"])
head = "<tr><th>Week of</th>" + "".join(f'<th><span class="tip {"tl" if i < 2 else "tr"}" tabindex="0" data-tip="{e(PDESC[p])}">{p}</span></th>' for i, p in enumerate(PRIOS)) + "<th>All issues opened/closed</th></tr>"
rows = "".join(f"<tr><td>{x['w']}</td>" + "".join(f"<td>{x['o' + p]:,}</td>" for p in PRIOS) + f"<td><b>{x['io']:,}/{x['ic']:,}</b></td></tr>" for x in reversed(W))
nowr = "<tr class='now'><td>Open now</td>" + "".join(f"<td>{open_prio[p]:,}</td>" for p in PRIOS) + f"<td><b>{open_issues:,} open</b></td></tr>"
now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
nowiso = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>SolidCraft stats</title><style>
:root{{color-scheme:light dark;--bg:#f6f7f9;--card:#fff;--fg:#1d2228;--mut:#667;--line:#e2e5ea}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111418;--card:#1b2026;--fg:#e6e9ee;--mut:#9aa3ad;--line:#2a3038}}}}
body{{margin:0;font:14px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--bg);color:var(--fg)}}
header{{padding:16px;display:flex;gap:16px;align-items:center;border-bottom:1px solid var(--line);flex-wrap:wrap}}h1{{font-size:18px;margin:0}}a{{color:#2f6fde}}.mut{{color:var(--mut);margin-left:auto}}
main{{padding:16px;display:grid;gap:18px;max-width:1200px}}section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;overflow:visible}}
h2{{font-size:14px;margin:0 0 8px}}.chart{{width:100%;height:auto}}.grid{{stroke:var(--line)}}.ax{{font-size:10px;fill:var(--mut)}}
.val{{font-size:10px;fill:var(--fg);font-weight:600;opacity:0}}.b:hover .val{{opacity:1}}.b:hover rect{{opacity:.8}}
.legend{{display:flex;gap:14px;font-size:12px;color:var(--mut)}}.lg i{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px}}
.kpis{{display:flex;gap:24px;flex-wrap:wrap;margin-bottom:8px}}.kpis b{{font-size:22px;display:block}}.kpis span{{color:var(--mut);font-size:12px}}
table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}th,td{{padding:4px 6px;border-top:1px solid var(--line);text-align:right;white-space:nowrap}}
th:first-child,td:first-child{{text-align:left}}tr.now td{{font-weight:600}}th{{position:relative}}
.tip{{text-decoration:underline dotted;cursor:pointer;position:relative;outline:none}}
.tip:hover::after,.tip:focus::after{{content:attr(data-tip);position:absolute;top:1.6em;z-index:5;width:220px;white-space:normal;text-align:left;font-weight:400;font-size:12px;padding:7px 9px;border-radius:8px;background:var(--fg);color:var(--bg)}}
.tip.tl::after{{left:-8px}}.tip.tr::after{{right:-8px}}
</style></head><body>
<header><h1>SolidCraft stats</h1><a href="./">← PR board</a><a href="https://tangency-labs.github.io/leaderboard/">Leaderboard</a><span class="mut">updated {now}<span class="ago" data-ts="{nowiso}"></span> (hourly, from GitHub search counts)</span></header>
<main>
<section><h2>Merge velocity: PRs merged per day (last {DAYS} days)</h2>{velocity()}</section>
<section><h2>PRs per week: opened / merged</h2>{prs_w}</section>
<section><h2>Issues per week: opened / closed</h2>{issues_w}</section>
<section><h2>Issues opened per week by priority</h2><table>{head}{nowr}{rows}</table></section>
</main><script>(function(){{function t(){{document.querySelectorAll(".ago").forEach(function(e){{var m=Math.max(0,Math.round((Date.now()-Date.parse(e.dataset.ts))/60000));e.textContent=" · "+(m<1?"just now":m<60?m+" minute"+(m==1?"":"s")+" ago":Math.floor(m/60)+" h "+(m%60)+" min ago");}});}}t();setInterval(t,30000);}})();</script></body></html>"""
os.makedirs(os.path.dirname(OUT), exist_ok=True)
open(OUT + ".tmp", "w").write(page); os.replace(OUT + ".tmp", OUT)
sys.exit(publish(OUT, DEST))
