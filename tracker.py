#!/usr/bin/env python3
"""
Internship opening tracker.

Polls the career job boards of the firms listed in config.json, compares the
result with the previously seen postings in state.json, and sends a phone
notification (ntfy.sh) plus a macOS notification whenever a firm posts a new
internship opening.

Designed to run unattended from launchd at 07:00 and 19:00. No third-party
packages required (works with the macOS system /usr/bin/python3).

Usage:
    python3 tracker.py            # normal run (first run baselines silently)
    python3 tracker.py --init     # force re-baseline: record everything, no alerts
    python3 tracker.py --test     # send a test notification and exit
    python3 tracker.py --dry-run  # fetch and diff, print instead of notifying
"""

import json
import hashlib
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
CONFIG_FILE = APP_DIR / "config.json"
STATE_FILE = APP_DIR / "state.json"
LOG_FILE = APP_DIR / "tracker.log"

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")

MAX_LOG_BYTES = 1_000_000


# --------------------------------------------------------------------------- #
# infrastructure
# --------------------------------------------------------------------------- #

def log(level, msg):
    line = "%s [%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), level, msg)
    print(line)
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_LOG_BYTES:
            tail = LOG_FILE.read_bytes()[-200_000:]
            LOG_FILE.write_bytes(b"...truncated...\n" + tail)
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def http_post_json(url, payload, timeout=30):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers={
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_state(state):
    tmp = STATE_FILE.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=1, ensure_ascii=False)
    tmp.replace(STATE_FILE)


def contains_any(text, keywords):
    if not keywords:
        return True
    low = text.lower()
    return any(k.lower() in low for k in keywords)


def strip_tags(html):
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html).strip()


# --------------------------------------------------------------------------- #
# source fetchers — each returns a list of postings:
#   {"id": str, "title": str, "location": str, "url": str}
# --------------------------------------------------------------------------- #

def fetch_workday(src):
    host, tenant, site = src["host"], src["tenant"], src["site"]
    api = "https://%s/wday/cxs/%s/%s/jobs" % (host, tenant, site)
    postings = {}
    for search in src.get("searches", [""]):
        offset, total = 0, None
        while True:
            data = http_post_json(api, {
                "appliedFacets": {}, "limit": 20, "offset": offset, "searchText": search})
            if total is None:
                total = data.get("total", 0)
            for p in data.get("jobPostings", []):
                path = p.get("externalPath")
                if not path:
                    continue
                postings[path] = {
                    "id": path,
                    "title": p.get("title", "").strip(),
                    "location": p.get("locationsText", "") or "",
                    "url": "https://%s/en-US/%s%s" % (host, site, path),
                }
            offset += 20
            if offset >= min(total, src.get("max_postings", 200)):
                break
            time.sleep(0.5)
    return list(postings.values())


def fetch_greenhouse(src):
    data = json.loads(http_get(
        "https://boards-api.greenhouse.io/v1/boards/%s/jobs" % src["board"]))
    out = []
    for j in data.get("jobs", []):
        out.append({
            "id": str(j["id"]),
            "title": j.get("title", "").strip(),
            "location": (j.get("location") or {}).get("name", "") or "",
            "url": j.get("absolute_url", ""),
        })
    return out


def fetch_50skills(src):
    data = json.loads(http_get(src["url"]))
    out = []
    for j in data:
        langs = j.get("languages") or [{}]
        title = langs[0].get("title", "").strip()
        desc = strip_tags(langs[0].get("shortDescriptionHtml", "") or
                          langs[0].get("shortDescription", "") or "")
        out.append({
            "id": str(j.get("id")),
            "title": title,
            "location": desc[:160],
            "url": j.get("url", ""),
        })
    return out


def fetch_oleeo(src):
    """Jefferies-style tal.net job board: postings appear as opp/<id>-<slug> links."""
    html = http_get(src["url"])
    out = {}
    for m in re.finditer(r'href="(https://[^"]*?/opp/(\d+)-([^/"]+)/en-GB)"', html):
        url, opp_id, slug = m.group(1), m.group(2), m.group(3)
        title = urllib.parse.unquote(slug).replace("-", " ").strip()
        out[opp_id] = {"id": opp_id, "title": title, "location": "", "url": url}
    if not out:
        # a live job board never lists zero openings — treat as a bad response
        raise RuntimeError("no postings found in page (%d bytes)" % len(html))
    return list(out.values())


def fetch_avature_rss(src):
    out = {}
    for feed in src["feeds"]:
        xml = http_get(feed)
        for m in re.finditer(
                r"<item>.*?<title><!\[CDATA\[(.*?)\]\]></title>.*?<link>(.*?)</link>.*?</item>",
                xml, re.S):
            title, link = m.group(1).strip(), m.group(2).strip()
            out[link] = {"id": link, "title": title, "location": "", "url": link}
    return list(out.values())


def fetch_sitemap_offers(src, state):
    """SocGen: find new /job-offers/ URLs in the sitemap; fetch only NEW pages whose
    slug looks internship-like, and keep those whose structured location field
    (JSON-LD addressLocality / dataLayer city) matches the target locations."""
    name = src["name"]
    rejected = set(state.get("rejected:" + name, []))
    known = state.get("known:" + name, {})       # url -> {"title","location"}
    xml = http_get(src["sitemap_url"])
    urls = re.findall(r"<loc>([^<]+)</loc>", xml)
    offers = [u for u in urls if "/job-offers/" in u and u.endswith("-en")]
    slug_kw = src.get("slug_keywords", ["intern"])
    loc_kw = src.get("location_keywords", [])
    out = []
    live = set()
    checked = 0
    for u in offers:
        slug = u.rsplit("/", 1)[-1]
        if not contains_any(slug, slug_kw) or u in rejected:
            continue
        live.add(u)
        if u in known:
            out.append({"id": u, "title": known[u]["title"],
                        "location": known[u]["location"], "url": u, "_known": True})
            continue
        if checked >= src.get("max_page_checks", 12):
            continue
        checked += 1
        try:
            page = http_get(u)
        except Exception:
            continue
        time.sleep(0.5)
        m_city = (re.search(r'"addressLocality"\s*:\s*"([^"]+)"', page) or
                  re.search(r'customVarPage2:\s*"([^"]+)"', page))
        city = m_city.group(1) if m_city else ""
        if contains_any(city, loc_kw):
            m_title = re.search(r'customVarPage1:\s*"([^"]+)"', page)
            title = m_title.group(1) if m_title else slug.replace("-", " ")
            known[u] = {"title": title, "location": city}
            out.append({"id": u, "title": title, "location": city, "url": u})
        else:
            rejected.add(u)
    # drop offers that left the sitemap (expired), keep memory bounded
    state["known:" + name] = {u: v for u, v in known.items() if u in live}
    state["rejected:" + name] = [u for u in rejected if u in live][-3000:]
    return out


def fetch_page_hash(src, state):
    """Victoria Partners: alert when the Praktikanten page content changes."""
    html = http_get(src["url"])
    text = strip_tags(html)
    marker = src.get("section_marker")
    if marker and marker.lower() in text.lower():
        idx = text.lower().index(marker.lower())
        text = text[idx:idx + 1500]
    digest = hashlib.sha256(text.encode()).hexdigest()
    key = "hash:" + src["name"]
    prev = state.get(key)
    state[key] = digest
    if prev is None or prev == digest:
        return []
    return [{
        "id": digest,
        "title": "Careers page content changed — check for new Praktikum openings",
        "location": "",
        "url": src["url"],
    }]


FETCHERS = {
    "workday": lambda src, state: fetch_workday(src),
    "greenhouse": lambda src, state: fetch_greenhouse(src),
    "50skills": lambda src, state: fetch_50skills(src),
    "oleeo": lambda src, state: fetch_oleeo(src),
    "avature_rss": lambda src, state: fetch_avature_rss(src),
    "sitemap_offers": fetch_sitemap_offers,
    "page_hash": fetch_page_hash,
}


# --------------------------------------------------------------------------- #
# filtering & notification
# --------------------------------------------------------------------------- #

def matches(src, posting, cfg):
    blob = "%s %s %s" % (posting["title"], posting["location"], posting["url"])
    title_kw = src.get("title_keywords")
    if title_kw is None:
        title_kw = cfg.get("intern_keywords", [])
    if title_kw and not contains_any(blob, title_kw):
        return False
    if not contains_any(blob, src.get("location_keywords", [])):
        return False
    return True


def ntfy_topic(cfg):
    """Topic resolution: env var (CI secret) > local git-ignored file > config."""
    import os
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        try:
            topic = (APP_DIR / ".ntfy-topic").read_text().strip()
        except OSError:
            pass
    return topic or cfg.get("notify", {}).get("ntfy_topic", "")


def send_ntfy(cfg, title, message, click_url=None):
    notify = cfg.get("notify", {})
    topic = ntfy_topic(cfg)
    if not topic:
        return False
    url = "%s/%s" % (notify.get("ntfy_server", "https://ntfy.sh").rstrip("/"), topic)
    headers = {
        "User-Agent": USER_AGENT,
        "Title": title.encode("ascii", "ignore").decode(),
        "Priority": "high",
        "Tags": "briefcase,rotating_light",
    }
    if click_url:
        headers["Click"] = click_url
    req = urllib.request.Request(url, data=message.encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        r.read()
    return True


def send_macos(title, message):
    if sys.platform != "darwin":
        return
    try:
        safe_t = title.replace("\\", "").replace('"', "'")
        safe_m = message.replace("\\", "").replace('"', "'")[:250]
        subprocess.run(
            ["osascript", "-e",
             'display notification "%s" with title "%s" sound name "Glass"'
             % (safe_m, safe_t)],
            capture_output=True, timeout=15)
    except Exception as e:
        log("WARN", "macOS notification failed: %s" % e)


def notify(cfg, title, message, click_url=None):
    ok = False
    try:
        ok = send_ntfy(cfg, title, message, click_url)
    except Exception as e:
        log("ERROR", "ntfy notification failed: %s" % e)
    if cfg.get("notify", {}).get("macos_notification", True):
        send_macos(title, message)
    return ok


# --------------------------------------------------------------------------- #
# status page
# --------------------------------------------------------------------------- #

STATUS_FILE = APP_DIR / "STATUS.md"


def local_now():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Zurich"))
    except Exception:
        return datetime.now()


def write_status(cfg, firm_status, state):
    now = local_now()
    lines = [
        "# Internship tracker — live status",
        "",
        "_Last check: %s_" % now.strftime("%Y-%m-%d %H:%M %Z").strip(),
        "",
        "| Firm | Open matching postings |",
        "|---|---|",
    ]
    for firm, info in firm_status.items():
        if info.get("error"):
            cell = "⚠️ source error (%d in a row)" % info["error"]
        elif info.get("watch"):
            cell = "👁 watching page for changes"
        elif info["postings"]:
            cell = "**%d open**" % len(info["postings"])
        else:
            cell = "—"
        lines.append("| %s | %s |" % (firm.replace("|", "\\|"), cell))

    open_lines = []
    for firm, info in firm_status.items():
        for p in info["postings"]:
            short_loc = p["location"][:60].rsplit(" ", 1)[0] if len(p["location"]) > 60 else p["location"]
            loc = (" — %s" % short_loc) if short_loc else ""
            open_lines.append("- **%s**: [%s](%s)%s" % (firm, p["title"], p["url"], loc))
    lines += ["", "## Currently open internships", ""]
    lines += open_lines if open_lines else ["_None right now._"]

    recent = state.get("recent_new", [])
    lines += ["", "## Alert history (newest first)", ""]
    if recent:
        for r in reversed(recent[-30:]):
            lines.append("- %s — **%s**: [%s](%s)"
                         % (r["ts"], r["firm"], r["title"], r["url"]))
    else:
        lines.append("_No alerts sent yet._")
    lines += ["", "_Checks run at ~07:00 and ~19:00. "
              "Edit config.json to add firms or locations._", ""]
    try:
        STATUS_FILE.write_text("\n".join(lines))
    except OSError as e:
        log("WARN", "could not write STATUS.md: %s" % e)


DASH_FILE = APP_DIR / "docs" / "index.html"

DASH_CSS = """
:root{--bg:#f5f6f8;--card:#fff;--tx:#1a1d21;--mut:#6b7280;--acc:#1d4ed8;
--ok:#047857;--okbg:#d1fae5;--line:#e5e7eb}
@media(prefers-color-scheme:dark){:root{--bg:#101216;--card:#1a1e24;--tx:#e7e9ec;
--mut:#9aa2ad;--acc:#7aa2ff;--ok:#34d399;--okbg:#0c3b2e;--line:#2a2f37}}
*{box-sizing:border-box;margin:0}
body{font:16px/1.5 -apple-system,system-ui,sans-serif;background:var(--bg);
color:var(--tx);padding:16px;padding-bottom:48px;max-width:640px;margin:0 auto}
h1{font-size:22px;margin:8px 0 2px}
.sub{color:var(--mut);font-size:13px;margin-bottom:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;
padding:14px 16px;margin-bottom:10px}
.firm{display:flex;justify-content:space-between;align-items:center;min-height:28px}
.badge{font-size:13px;font-weight:600;color:var(--ok);background:var(--okbg);
border-radius:999px;padding:3px 10px;white-space:nowrap}
.dash{color:var(--mut)}
h2{font-size:15px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut);
margin:22px 0 10px}
a.job{display:block;text-decoration:none;color:inherit;padding:12px 16px;
background:var(--card);border:1px solid var(--line);border-radius:14px;
margin-bottom:8px}
a.job b{color:var(--acc);font-size:13px;display:block}
a.job span{color:var(--mut);font-size:13px;display:block}
.hist{font-size:13px;color:var(--mut);padding:6px 2px}
.hist a{color:var(--acc);text-decoration:none}
"""


def write_dashboard(cfg, firm_status, state):
    now = local_now()
    esc = lambda s: (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    firms_html = []
    for firm, info in firm_status.items():
        if info.get("error"):
            right = '<span class="badge" style="color:#b45309;background:#fef3c7">source error</span>'
        elif info.get("watch"):
            right = '<span class="dash">watching page</span>'
        elif info["postings"]:
            right = '<span class="badge">%d open</span>' % len(info["postings"])
        else:
            right = '<span class="dash">&mdash;</span>'
        firms_html.append('<div class="card firm"><div>%s</div>%s</div>'
                          % (esc(firm), right))

    jobs_html = []
    for firm, info in firm_status.items():
        for p in info["postings"]:
            loc = p["location"][:60]
            jobs_html.append(
                '<a class="job" href="%s"><b>%s</b>%s<span>%s</span></a>'
                % (p["url"], esc(firm), esc(p["title"]), esc(loc)))
    if not jobs_html:
        jobs_html = ['<div class="card dash">None right now.</div>']

    hist_html = []
    for r in reversed(state.get("recent_new", [])[-30:]):
        hist_html.append('<div class="hist">%s &middot; <a href="%s">%s — %s</a></div>'
                         % (r["ts"], r["url"], esc(r["firm"]), esc(r["title"])))
    if not hist_html:
        hist_html = ['<div class="hist">No alerts sent yet.</div>']

    html = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1,viewport-fit=cover\">"
            "<meta name=\"apple-mobile-web-app-capable\" content=\"yes\">"
            "<meta name=\"apple-mobile-web-app-status-bar-style\" content=\"default\">"
            "<link rel=\"apple-touch-icon\" href=\"icon.png\">"
            "<title>Internships</title><style>%s</style></head><body>"
            "<h1>Internship tracker</h1>"
            "<div class=\"sub\">Last check: %s &middot; runs ~07:00 &amp; ~19:00</div>"
            "%s<h2>Open internships</h2>%s<h2>Alert history</h2>%s"
            "</body></html>") % (
        DASH_CSS, now.strftime("%a %d %b, %H:%M %Z").strip(),
        "".join(firms_html), "".join(jobs_html), "".join(hist_html))
    try:
        DASH_FILE.parent.mkdir(exist_ok=True)
        DASH_FILE.write_text(html)
    except OSError as e:
        log("WARN", "could not write dashboard: %s" % e)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def run(baseline=False, dry_run=False):
    cfg = load_json(CONFIG_FILE, None)
    if cfg is None:
        log("ERROR", "config.json missing or invalid — aborting")
        return 1
    state = load_json(STATE_FILE, {})
    first_run = not STATE_FILE.exists()
    if first_run:
        baseline = True

    all_new = []          # (firm, posting)
    failures = state.setdefault("failures", {})
    firm_status = {}      # firm -> {"postings": [...], "error": n, "watch": bool}

    for src in cfg.get("sources", []):
        name, firm, typ = src["name"], src["firm"], src["type"]
        if not src.get("enabled", True):
            continue
        try:
            postings = FETCHERS[typ](src, state)
            failures[name] = 0
        except Exception as e:
            failures[name] = failures.get(name, 0) + 1
            log("ERROR", "%s: fetch failed (%d consecutive): %s" % (name, failures[name], e))
            firm_status[firm] = {"postings": [], "error": failures[name]}
            if failures[name] == 3 and not dry_run:
                notify(cfg, "Internship tracker: source failing",
                       "%s has failed 3 runs in a row (%s). Check tracker.log — "
                       "the site layout may have changed." % (firm, e))
            continue

        seen_key = "seen:" + name
        seen = set(state.get(seen_key, []))
        matched, new_here = [], []
        for p in postings:
            if p.get("_suppress"):
                seen.add(p["id"])
                continue
            # page_hash and sitemap_offers filter inside the fetcher itself
            if typ in ("page_hash", "sitemap_offers") or matches(src, p, cfg):
                matched.append(p)
                if p["id"] not in seen and not p.get("_known"):
                    new_here.append(p)
                seen.add(p["id"])

        # cap state growth
        state[seen_key] = list(seen)[-2000:]
        log("INFO", "%s: %d postings fetched, %d matched, %d new"
            % (name, len(postings), len(matched), len(new_here)))
        firm_status[firm] = {"postings": [] if typ == "page_hash" else matched,
                             "watch": typ == "page_hash"}
        for p in new_here:
            all_new.append((firm, p))

    if all_new:
        if baseline:
            log("INFO", "baseline run: %d matching postings recorded without alerting"
                % len(all_new))
        elif dry_run:
            for firm, p in all_new:
                print("WOULD NOTIFY: %s — %s %s %s"
                      % (firm, p["title"], p["location"], p["url"]))
        else:
            lines = []
            for firm, p in all_new:
                loc = (" — " + p["location"][:60]) if p["location"] else ""
                lines.append("%s: %s%s\n%s" % (firm, p["title"], loc, p["url"]))
            firms = sorted({f for f, _ in all_new})
            if len(all_new) == 1:
                title = "New internship opening: %s" % firms[0]
                click = all_new[0][1]["url"]
            else:
                title = "%d new internship openings (%s)" % (len(all_new), ", ".join(firms))
                click = None
            notify(cfg, title, "\n\n".join(lines), click)
            log("INFO", "notified: %s" % title)
            recent = state.setdefault("recent_new", [])
            ts = local_now().strftime("%Y-%m-%d %H:%M")
            for firm, p in all_new:
                recent.append({"ts": ts, "firm": firm,
                               "title": p["title"], "url": p["url"]})
            state["recent_new"] = recent[-30:]

    write_status(cfg, firm_status, state)
    write_dashboard(cfg, firm_status, state)
    state["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    state["last_new_count"] = len(all_new)
    if not dry_run:
        save_state(state)
    if first_run and not dry_run:
        notify(cfg, "Internship tracker is live",
               "Monitoring %d sources for internship openings. Current matching "
               "postings were recorded as baseline; you will be alerted about "
               "anything new." % len(cfg.get("sources", [])))
    return 0


def main():
    args = sys.argv[1:]
    if "--test" in args:
        cfg = load_json(CONFIG_FILE, {})
        ok = notify(cfg, "Internship tracker: test",
                    "Test notification — your phone is connected correctly.")
        print("ntfy delivery:", "ok" if ok else "FAILED (check config)")
        return 0
    if "--init" in args:
        try:
            STATE_FILE.unlink()
        except FileNotFoundError:
            pass
        return run(baseline=True)
    return run(dry_run="--dry-run" in args)


if __name__ == "__main__":
    sys.exit(main())
