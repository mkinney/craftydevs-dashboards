#!/usr/bin/env python3
"""CamCraft stats page: issues opened/closed by priority and PRs opened/merged per day and week, from `gh` only (no AI).
Runs hourly from cron and publishes https://craftydevs.org/camcraft/status/stats.html (user, 2026-11-16)."""
import collections, datetime as dt, html, json, os, subprocess, sys

R = "NeoTech/Camcraft"
GH = next((p for p in ("/opt/homebrew/bin/gh", "/usr/local/bin/gh") if os.path.exists(p)), "gh")
OUT = os.path.expanduser(os.environ.get("CAMCRAFT_STATS_OUT", "~/dashboards/camcraft/stats.html"))
DEST = os.environ.get("CAMCRAFT_STATS_DEST", "")
DAYS, WEEKS = 21, 10
PRIOS = ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P?", "none"]



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


def day(ts):
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).date() if ts else None


issues = gh("issue", "list", "-R", R, "--state", "all", "--limit", "5000", "--json", "number,createdAt,closedAt,labels,stateReason")
prs = gh("pr", "list", "-R", R, "--state", "all", "--limit", "5000", "--json", "number,createdAt,closedAt,mergedAt,author")

today = dt.datetime.now(dt.timezone.utc).date()
days = [today - dt.timedelta(d) for d in range(DAYS - 1, -1, -1)]
wk = lambda d: d - dt.timedelta(d.weekday())
weeks = [wk(today) - dt.timedelta(7 * w) for w in range(WEEKS - 1, -1, -1)]


def prio(i):
    L = [l["name"] for l in i["labels"]]
    return next((p for p in PRIOS if p in L), "none")


c = collections.Counter()
for i in issues:
    p, o, x = prio(i), day(i["createdAt"]), day(i["closedAt"])
    c[("io", o)] += 1; c[("io", wk(o))] += 0
    c[("iow", wk(o), p)] += 1; c[("iod", o)] += 1
    if x:
        c[("icw", wk(x), p)] += 1; c[("icd", x)] += 1
for p in prs:
    o, m, x = day(p["createdAt"]), day(p["mergedAt"]), day(p["closedAt"])
    who = p["author"]["login"] if p["author"]["login"] in ("mkinney", "NeoTech") else "contributors"
    c[("pod", o)] += 1; c[("pow", wk(o), who)] += 1
    if m:
        c[("pmd", m)] += 1; c[("pmw", wk(m), who)] += 1
    elif x:
        c[("pxd", x)] += 1; c[("pxw", wk(x), who)] += 1

open_now = collections.Counter(prio(i) for i in issues if not i["closedAt"])
open_prs = collections.Counter((p["author"]["login"] if p["author"]["login"] in ("mkinney", "NeoTech") else "contributors")
                               for p in prs if not p["closedAt"])
e = html.escape


def bars(series, labels, colors, h=120):
    """Grouped bar chart as inline SVG: series = [(name, [values])]."""
    n, g = len(labels), len(series)
    mx = max([1] + [v for _, vs in series for v in vs])
    bw, gap, left, top, bottom = 12, 10, 34, 18, 46
    W = left + n * (g * bw + gap) + 10          # room for the last day (it was cut off)
    out = [f'<svg viewBox="0 0 {W} {top + h + bottom}" class="chart" role="img">']
    for k in range(5):
        y = top + h - h * k / 4
        out.append(f'<line x1="{left - 4}" x2="{W}" y1="{y:.0f}" y2="{y:.0f}" class="grid"/>'
                   f'<text x="{left - 6}" y="{y + 3:.0f}" class="ax" text-anchor="end">{round(mx * k / 4):,}</text>')
    for j, lab in enumerate(labels):
        x0 = left + j * (g * bw + gap)
        for s, (name, vs) in enumerate(series):
            v = vs[j]; bh = h * v / mx; y = top + h - bh
            # hover (or tap) a bar: its value shows above it; the <title> is the native tooltip too
            out.append(f'<g class="b"><rect x="{x0 + s * bw}" y="{y:.1f}" width="{bw - 2}" height="{max(bh, 0.5):.1f}" fill="{colors[s]}">'
                       f'<title>{e(name)} {e(lab)}: {v:,}</title></rect>'
                       f'<text x="{x0 + s * bw + (bw - 2) / 2:.1f}" y="{y - 3:.1f}" class="val" text-anchor="middle">{v:,}</text></g>')
        cx = x0 + (g * bw) / 2
        out.append(f'<text x="{cx:.1f}" y="{top + h + 8}" class="ax" text-anchor="end" '
                   f'transform="rotate(-55 {cx:.1f} {top + h + 8})">{e(lab)}</text>')
    out.append("</svg>")
    leg = "".join(f'<span class="lg"><i style="background:{col}"></i>{e(nm)}</span>' for (nm, _), col in zip(series, colors))
    return "".join(out) + f'<div class="legend">{leg}</div>'


try:
    ST = json.load(open(os.path.expanduser(os.environ.get("DASH_STATUS", "~/dashboards/status.json"))))
except Exception:
    ST = {}
DD = ST.get("done_days", {})
JOBK = [("fixup", "fixups", "#e07b14"), ("mergefix", "refreshes", "#8a94a3"), ("review", "reviews", "#2f6fde"),
        ("work", "issues worked", "#1f9d55"), ("research", "research", "#6b4fd8")]
dl = [d.strftime("%m-%d") for d in days]
wl = [w.strftime("%m-%d") for w in weeks]
issue_daily = bars([("opened", [c[("iod", d)] for d in days]), ("closed", [c[("icd", d)] for d in days])], dl, ["#2f6fde", "#1f9d55"])
def merge_velocity():
    """PRs merged to main per day since the first merge: a thin daily line plus a 7-day average."""
    md = collections.Counter(day(p["mergedAt"]) for p in prs if p["mergedAt"])
    if not md:
        return "<p>No merges yet.</p>"
    d0, d1 = min(md), today
    ds = [d0 + dt.timedelta(i) for i in range((d1 - d0).days + 1)]
    v = [md.get(d, 0) for d in ds]
    avg = [sum(v[max(0, i - 6):i + 1]) / len(v[max(0, i - 6):i + 1]) for i in range(len(v))]
    W, H, L, T, B = 820, 170, 34, 14, 46
    mx = max(max(v), 1)
    X = lambda i: L + (W - L - 10) * (i / max(1, len(ds) - 1))
    Y = lambda y: T + H - H * y / mx
    out = [f'<svg viewBox="0 0 {W} {T + H + B}" class="chart" role="img">']
    for k in range(5):
        y = T + H - H * k / 4
        out.append(f'<line x1="{L - 4}" x2="{W}" y1="{y:.0f}" y2="{y:.0f}" class="grid"/><text x="{L - 6}" y="{y + 3:.0f}" class="ax" text-anchor="end">{round(mx * k / 4):,}</text>')
    pts = lambda arr: " ".join(f"{X(i):.1f},{Y(a):.1f}" for i, a in enumerate(arr))
    out.append(f'<polyline points="{pts(v)}" fill="none" stroke="#2f6fde" stroke-opacity=".45" stroke-width="1.5"/>')
    out.append(f'<polyline points="{pts(avg)}" fill="none" stroke="#1f9d55" stroke-width="3"/>')
    step = max(1, len(ds) // 14)
    for i, d in enumerate(ds):
        out.append(f'<g class="b"><circle cx="{X(i):.1f}" cy="{Y(v[i]):.1f}" r="5" fill="transparent"/><circle cx="{X(i):.1f}" cy="{Y(v[i]):.1f}" r="2" fill="#2f6fde"/>'
                   f'<title>{d}: {v[i]:,} merged · 7-day avg {avg[i]:.1f}</title>'
                   f'<text x="{X(i):.1f}" y="{Y(v[i]) - 7:.1f}" class="val" text-anchor="middle">{v[i]:,}</text></g>')
        if i % step == 0 or i == len(ds) - 1:
            out.append(f'<text x="{X(i):.1f}" y="{T + H + 10}" class="ax" text-anchor="end" transform="rotate(-55 {X(i):.1f} {T + H + 10})">{d.strftime("%m-%d")}</text>')
    out.append("</svg>")
    tot, last7 = sum(v), sum(v[-7:])
    prev7 = sum(v[-14:-7])
    trend = "↑" if last7 > prev7 else ("↓" if last7 < prev7 else "→")
    head = (f'<div class="kpis"><div><b>{last7:,}</b><span>merged, last 7 days {trend} (prior 7: {prev7:,})</span></div>'
            f'<div><b>{avg[-1]:.1f}</b><span>per day, 7-day average</span></div><div><b>{tot:,}</b><span>merged since {d0}</span></div></div>')
    leg = ('<div class="legend"><span class="lg"><i style="background:#2f6fde;opacity:.5"></i>merged per day</span>'
           '<span class="lg"><i style="background:#1f9d55"></i>7-day average</span></div>')
    return head + "".join(out) + leg


jobs_daily = bars([(lab, [DD.get(d.isoformat(), {}).get(k, 0) for d in days]) for k, lab, _ in JOBK], dl, [c_ for _, _, c_ in JOBK]) if DD else "<p>No data yet.</p>"
pr_daily = bars([("opened", [c[("pod", d)] for d in days]), ("merged", [c[("pmd", d)] for d in days]),
                 ("closed unmerged", [c[("pxd", d)] for d in days])], dl, ["#2f6fde", "#1f9d55", "#8a94a3"])


def ptable():
    PDESC = {
        "P1": "P1: unsafe or wrong output - a gouge or collision that passes, wrong posted G-code, a crash, data loss",
        "P2": "P2: main is broken, or the last release has a regression with no workaround",
        "P3": "P3: wrong behaviour a user hits, with a workaround (a legal program refused, a misleading message)",
        "P4": "P4: work the maintainer asked for, for the next cut",
        "P5": "P5: the agent surface and tooling keep up with what shipped (MCP tools, skills, gate/process fixes)",
        "P6": "P6: accepted enhancements, not scheduled",
        "P7": "P7: owed polish and small fixes - wording, layout, a missing test",
        "P8": "P8: larger ideas that need design or research before code",
        "P9": "P9: someday - not picked while other work is free",
        "P?": "P?: paused - held by the maintainer until he sets a priority",
        "none": "none: not triaged yet (no priority label)",
    }
    head = "<tr><th>Week of</th>" + "".join(f'<th><span class="tip {"tl" if i < 6 else "tr"}" tabindex="0" data-tip="{e(PDESC[p])}">{p}</span></th>' for i, p in enumerate(PRIOS)) + "<th>All</th></tr>"
    rows = []
    for w in reversed(weeks):
        cells, to, tc = [], 0, 0
        for p in PRIOS:
            o, x = c[("iow", w, p)], c[("icw", w, p)]
            to += o; tc += x
            cells.append(f"<td>{(format(o, ',') if o else '')}{'/' if o or x else ''}{(format(x, ',') if x else '')}</td>")
        rows.append(f"<tr><td>{w}</td>{''.join(cells)}<td><b>{to:,}/{tc:,}</b></td></tr>")
    nowr = "<tr class='now'><td>Open now</td>" + "".join(f"<td>{format(open_now[p], ',') if open_now.get(p) else ''}</td>" for p in PRIOS) + f"<td><b>{sum(open_now.values()):,}</b></td></tr>"
    return f"<div class='tablewrap'><table>{head}{nowr}{''.join(rows)}</table></div>"


def prtable():
    who = ["mkinney", "NeoTech", "contributors"]
    head = "<tr><th>Week of</th>" + "".join(f"<th>{w}<br><small>opened/merged/closed</small></th>" for w in who) + "</tr>"
    rows = []
    for w in reversed(weeks):
        rows.append(f"<tr><td>{w}</td>" + "".join(f"<td>{c[('pow', w, a)]:,}/{c[('pmw', w, a)]:,}/{c[('pxw', w, a)]:,}</td>" for a in who) + "</tr>")
    nowr = "<tr class='now'><td>Open now</td>" + "".join(f"<td>{open_prs.get(a, 0):,}</td>" for a in who) + "</tr>"
    return f"<table>{head}{nowr}{''.join(rows)}</table>"


now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
nowiso = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>CamCraft stats</title><style>.gh{{display:inline-flex;align-items:center;color:var(--mut);text-decoration:none;padding:4px}}.gh:hover{{color:var(--fg)}}.gh svg{{width:20px;height:20px;fill:currentColor}}
:root{{color-scheme:light dark;--bg:#f6f7f9;--card:#fff;--fg:#1d2228;--mut:#667;--line:#e2e5ea}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111418;--card:#1b2026;--fg:#e6e9ee;--mut:#9aa3ad;--line:#2a3038}}}}
body{{margin:0;font:14px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--bg);color:var(--fg)}}
header{{padding:16px;display:flex;gap:16px;align-items:center;border-bottom:1px solid var(--line);flex-wrap:wrap}}
h1{{font-size:18px;margin:0}}a{{color:#2f6fde}}.mut{{color:var(--mut);margin-left:auto}}
main{{padding:16px;display:grid;gap:18px;max-width:1200px}}section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;overflow-x:auto}}
h2{{font-size:14px;margin:0 0 8px}}.chart{{width:100%;height:auto}}.grid{{stroke:var(--line)}}.ax{{font-size:10px;fill:var(--mut)}}.val{{font-size:10px;fill:var(--fg);font-weight:600;opacity:0}}.b:hover .val,.b:focus .val{{opacity:1}}.b:hover rect{{opacity:.8}}
.legend{{display:flex;gap:14px;font-size:12px;color:var(--mut)}}.lg i{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px}}
table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}th,td{{padding:4px 6px;border-top:1px solid var(--line);text-align:right;white-space:nowrap}}
th:first-child,td:first-child{{text-align:left}}tr.now td{{font-weight:600}}.kpis{{display:flex;gap:24px;flex-wrap:wrap;margin-bottom:8px}}.kpis b{{font-size:22px;display:block}}.kpis span{{color:var(--mut);font-size:12px}}th{{position:relative}}.tip{{text-decoration:underline dotted;cursor:pointer;position:relative;outline:none}}.tip:hover::after,.tip:focus::after{{content:attr(data-tip);position:absolute;top:1.6em;z-index:5;width:260px;white-space:normal;text-align:left;font-weight:400;font-size:12px;line-height:1.35;padding:7px 9px;border-radius:8px;background:var(--fg);color:var(--bg);box-shadow:0 4px 14px rgba(0,0,0,.25)}}section{{overflow:visible}}.tip.tl::after{{left:-8px}}.tip.tr::after{{right:-8px}}.tablewrap{{overflow-x:auto;padding-bottom:90px;margin-bottom:-90px}}small{{color:var(--mut);font-weight:400}}
</style></head><body>
<header><h1>CamCraft stats</h1><a href="./">← PR board</a><span class="mut">{len(issues):,} issues · {len(prs):,} PRs · updated {now}<span class="ago" data-ts="{nowiso}"></span> (hourly)</span><a class="gh" href="https://github.com/mkinney/craftydevs-dashboards" title="Source of these pages on GitHub" aria-label="Source of these pages on GitHub"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg></a></header>
<main>
<section><h2>Merge velocity: PRs merged to main</h2>{merge_velocity()}</section>
<section><h2>Issues per day (last {DAYS} days)</h2>{issue_daily}</section>
<section><h2>Issues by priority, per week: opened/closed</h2>{ptable()}</section>
<section><h2>PRs per day (last {DAYS} days)</h2>{pr_daily}</section>
<section><h2>PRs per week by author</h2>{prtable()}</section>
<section><h2>Agent jobs finished per day (velocity)</h2>{jobs_daily}<p class="mut">Each job counted once per PR per day. Earlier days only count what the job logs still hold.</p></section>
</main><script>(function(){{function t(){{document.querySelectorAll(".ago").forEach(function(e){{var m=Math.max(0,Math.round((Date.now()-Date.parse(e.dataset.ts))/60000));e.textContent=" · "+(m<1?"just now":m<60?m+" minute"+(m==1?"":"s")+" ago":Math.floor(m/60)+" h "+(m%60)+" min ago");}});}}t();setInterval(t,30000);}})();</script></body></html>"""

os.makedirs(os.path.dirname(OUT), exist_ok=True)
open(OUT + ".tmp", "w").write(page)
os.replace(OUT + ".tmp", OUT)
sys.exit(publish(OUT, DEST))
