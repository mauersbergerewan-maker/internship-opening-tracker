# Internship Opening Tracker

Watches the career job boards of the firms from your coffee-chat list and alerts
your phone the moment one of them posts a new internship opening.

**➡️ Live dashboard: [STATUS.md](STATUS.md)** — current openings per firm,
updated on every check. Bookmark on your phone:
<https://github.com/mauersbergerewan-maker/internship-opening-tracker/blob/main/STATUS.md>

## Where it runs

GitHub Actions runs `tracker.py` **in the cloud at ~07:00 and ~19:00**
(see `.github/workflows/check.yml`), independent of any laptop being on.
Each run commits the updated `state.json` and `STATUS.md` back to this repo.
You can also trigger a check manually from the Actions tab ("Run workflow").

## What it monitors (from `config.json`)

| Firm | Source | Filter |
|---|---|---|
| Baird | Workday API | Intern + Frankfurt/Germany |
| Harris Williams | Workday API (own board) | Intern/Off-Cycle + Frankfurt |
| Houlihan Lokey | Workday Campus board | Intern + Frankfurt/Germany (covers Debt Advisory) |
| Rothschild & Co | Workday **Interns board** (currently empty — expected to open ~01.08) | Any posting in Frankfurt/Germany |
| Jefferies | tal.net job board | Internship + Frankfurt |
| Macquarie | Avature RSS feeds | Intern + Frankfurt/Germany keywords |
| Société Générale CIB | Careers sitemap → offer pages | Intern slugs mentioning Frankfurt or London |
| Victoria Partners | Praktikanten page change detection | Any change to the "Aktuelle Stellenangebote" section |
| Stifel | 50skills JSON API | Intern + Frankfurt/Munich/Germany |
| Alantra | Workday API | Intern + Frankfurt/Germany |
| Mizuho \| Greenhill | Mizuho Workday board | Intern + Frankfurt/Germany |
| Riverside Company | Greenhouse API | Intern + Riverside Europe offices |

## Phone notifications — one-time setup (2 minutes)

Notifications are sent through [ntfy.sh](https://ntfy.sh) (free, no account needed):

1. Install the **ntfy** app on your phone (App Store / Play Store).
2. In the app tap **+ / Subscribe to topic** and enter exactly:

   ```
   internships-ewan-b36b3dc9
   ```

3. Test it: `python3 ~/InternshipTracker/tracker.py --test`

The topic name is random so nobody else will guess it. You also get a macOS
notification on this Mac as a backup, so nothing is missed while you set up ntfy.

## Schedule

A launchd agent (`com.ewan.internship-tracker`) runs the check **every day at
07:00 and 19:00** local time. If the Mac is asleep at that moment, macOS runs
the missed check as soon as it wakes up — you'll get the alert then.

Manage it:

```bash
# check it is loaded
launchctl list | grep internship

# run a check right now
python3 ~/InternshipTracker/tracker.py

# uninstall
launchctl bootout gui/$(id -u)/com.ewan.internship-tracker
rm ~/Library/LaunchAgents/com.ewan.internship-tracker.plist
```

## Files

- `tracker.py` — the application (no dependencies, runs on the system Python)
- `config.json` — firms, endpoints, keyword filters, notification settings
- `state.json` — postings already seen (auto-created; delete to re-baseline)
- `tracker.log` — run history; check here if something looks off
- `launchd.log` — output of the scheduled runs

## Adjusting

- **Add/remove locations** (e.g. include London for Jefferies): edit the
  `location_keywords` of that source in `config.json`.
- **Add a firm on Workday**: copy any workday block and change `host`, `tenant`,
  `site` (from the firm's job page URL: `https://TENANT.wdN.myworkdayjobs.com/SITE`).
- **Disable a source**: add `"enabled": false` to its block.
- If a source breaks (site redesign), you get **one** warning notification after
  3 failed runs in a row — then check `tracker.log`.

## Trackers that could not be automated

- **EMERGERS** (emergers.de/tracker) — members-only; the public page has no data.
  Worth joining manually, they push openings to members.
- **fyntraq** (fyntraq.io) — requires an account; you can create one yourself and
  turn on its own e-mail alerts as a second safety net.
