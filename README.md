# craftydevs-dashboards

Static status pages for two open-source CAD/CAM projects, built from the GitHub API with the `gh` CLI and
published as plain HTML. No database, no server code, no AI: a cron job rebuilds each page and copies it to any
web host that takes `rsync`.

Live at [craftydevs.org](https://craftydevs.org/):

| Page | Script | Suggested schedule | GitHub API cost |
|---|---|---|---|
| [CamCraft PR board](https://craftydevs.org/camcraft/status/) | `camcraft_board.py` | every minute | a few GraphQL points per run |
| [CamCraft stats](https://craftydevs.org/camcraft/status/stats.html) | `camcraft_stats.py` | hourly | ~7 GraphQL points per run |
| [SolidCraft PR board](https://craftydevs.org/solidcraft/status/) | `solidcraft_board.py` | every 15 minutes | ~3 GraphQL points per run |
| [SolidCraft stats](https://craftydevs.org/solidcraft/status/stats.html) | `solidcraft_stats.py` | hourly | ~130 search calls, paced to stay under 30/minute (~6 min per run) |

## What the pages show

- **PR boards:** open pull requests in columns by review state (ready to merge, in review, needs rework,
  conflicts, waiting on a maintainer, draft), recent merges, and open P1-P3 bugs (CamCraft). Each page shows when
  it was rebuilt ("x minutes ago") and has an optional auto-refresh toggle.
- **Stats pages:** merge velocity (PRs merged per day with a 7-day average), PRs and issues opened/closed per day
  or week, and issues by priority. Bar values show on hover.
- **CamCraft board extras** (optional): if a `status.json` file exists (`DASH_STATUS`), the board shows a strip
  with worker activity and per-PR "running" pills. Without the file, the strip is hidden. The board also shows
  `agent/*` commit statuses as pills (a convention for "an agent is working on this PR").

## Run it

Needs Python 3.9+ (standard library only) and the [GitHub CLI](https://cli.github.com/) logged in (`gh auth login`).

```sh
python3 camcraft_board.py            # writes ~/dashboards/camcraft/index.html
CAMCRAFT_BOARD_DEST=user@host:public_html/camcraft/status/index.html python3 camcraft_board.py   # and publishes it
```

Each script reads two environment variables:

| Script | Output file (default) | Publish target (empty = don't publish) |
|---|---|---|
| `camcraft_board.py` | `CAMCRAFT_BOARD_OUT` (`~/dashboards/camcraft/index.html`) | `CAMCRAFT_BOARD_DEST` |
| `camcraft_stats.py` | `CAMCRAFT_STATS_OUT` (`~/dashboards/camcraft/stats.html`) | `CAMCRAFT_STATS_DEST` |
| `solidcraft_board.py` | `SOLIDCRAFT_BOARD_OUT` (`~/dashboards/solidcraft/index.html`) | `SOLIDCRAFT_BOARD_DEST` |
| `solidcraft_stats.py` | `SOLIDCRAFT_STATS_OUT` (`~/dashboards/solidcraft/stats.html`) | `SOLIDCRAFT_STATS_DEST` |

The target is anything `rsync` accepts, usually `user@host:path` with an SSH key. See `crontab.example`.

To point a page at another repository, change the repository constant at the top of the script (`R`).

## License

MIT - see `LICENSE`.
