#!/usr/bin/env python3
"""
Encore: a ticket deal watcher with a dashboard.

Checks SeatGeek's official API for popular pop / adult contemporary concerts and
comedy shows near Houston, Dallas and Austin, and sends a push notification to
your phone (through the free ntfy app) when prices look good.

It never buys anything. It tells you, and you tap the link and buy.

Two sources:
  SeatGeek     - resale prices: "good seats in budget" and "price drop" alerts
  Ticketmaster - "new show announced" and "presale / on-sale starts soon" alerts

Settings live in config.json. Secrets come from environment variables:
  SEATGEEK_CLIENT_ID    - your SeatGeek developer client ID
  TICKETMASTER_API_KEY  - your Ticketmaster "Consumer Key" (optional)
  NTFY_TOPIC            - the private topic name you subscribed to in the ntfy app

Usage:
  python ticket_bot.py               normal run (check prices, send alerts)
  python ticket_bot.py --test-notify just send one test notification
  python ticket_bot.py --dry-run     check prices and print alerts, send nothing
"""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
STATE_PATH = os.path.join(HERE, "state.json")
SEATGEEK_URL = "https://api.seatgeek.com/2/events"
NTFY_URL = "https://ntfy.sh/"
PER_PAGE = 100


# ---------------------------------------------------------------- helpers

def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def http_get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "personal-ticket-alert-bot"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def money(value):
    return "n/a" if value is None else f"${value:,.0f}"


def nice_date(local_iso):
    try:
        dt = datetime.fromisoformat(local_iso)
        return dt.strftime("%a %b %-d, %-I:%M %p")
    except (TypeError, ValueError):
        return local_iso or "date TBD"


# ---------------------------------------------------------------- SeatGeek

def fetch_events(client_id, city, taxonomy, cfg):
    """Return events for one city + category, most popular first."""
    now = datetime.now(timezone.utc)
    until = now + timedelta(days=cfg["days_ahead"])
    found = []
    for page in range(1, cfg.get("max_pages", 5) + 1):
        params = {
            "client_id": client_id,
            "lat": city["lat"],
            "lon": city["lon"],
            "range": f"{cfg['radius_miles']}mi",
            "taxonomies.name": taxonomy,
            "datetime_utc.gte": now.strftime("%Y-%m-%dT%H:%M:%S"),
            "datetime_utc.lte": until.strftime("%Y-%m-%dT%H:%M:%S"),
            "sort": "score.desc",
            "per_page": PER_PAGE,
            "page": page,
        }
        data = http_get_json(SEATGEEK_URL + "?" + urllib.parse.urlencode(params))
        batch = data.get("events", [])
        found.extend(batch)
        # Results are sorted by popularity, so once we're below the cutoff, stop.
        if len(batch) < PER_PAGE or (batch and (batch[-1].get("score") or 0) < cfg["min_popularity_score"]):
            break
    return found


def performer_names(event):
    return [p.get("name", "") for p in event.get("performers", [])]


def genre_names(event):
    names = []
    for p in event.get("performers", []):
        for g in p.get("genres", []) or []:
            names.append((g.get("name") or g.get("slug") or "").lower())
    return names


def name_matches(event, names_list):
    haystack = " ".join([event.get("title", "")] + performer_names(event)).lower()
    return any(n.lower() in haystack for n in names_list if n.strip())


def wanted(event, taxonomy, cfg):
    """Decide whether this event is one Ben cares about."""
    if name_matches(event, cfg.get("never_watch", [])):
        return False
    if name_matches(event, cfg.get("always_watch", [])):
        return True
    if (event.get("score") or 0) < cfg["min_popularity_score"]:
        return False
    if taxonomy == "comedy":
        return True
    genres = genre_names(event)
    return any(k.lower() in g for g in genres for k in cfg["concert_genre_keywords"])


# ---------------------------------------------------------------- alerts

def describe(event, city_name):
    venue = event.get("venue", {}) or {}
    stats = event.get("stats", {}) or {}
    where = venue.get("name", "Unknown venue")
    venue_city = venue.get("city") or city_name
    return (
        f"{where}, {venue_city}\n"
        f"{nice_date(event.get('datetime_local'))}\n"
        f"Cheapest {money(stats.get('lowest_price'))} · "
        f"Typical (median) {money(stats.get('median_price'))} · "
        f"{stats.get('listing_count') or 0} listings"
    )


def _hours_later(iso_stamp, hours):
    try:
        dt = datetime.fromisoformat(iso_stamp.replace("Z", "+00:00")) + timedelta(hours=hours)
        return dt.strftime("%Y-%m-%dT%H")
    except (ValueError, AttributeError):
        return ""


def days_until(utc_iso):
    if not utc_iso:
        return None
    try:
        dt = datetime.fromisoformat(utc_iso.replace("Z", "")).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (dt - datetime.now(timezone.utc)).total_seconds() / 86400


def short_title(event):
    performers = performer_names(event)
    return performers[0] if performers else event.get("title", "Event")


def is_premium(event, cfg):
    """Biggest acts (very high popularity score) and K-pop get the higher budget."""
    if (event.get("score") or 0) >= cfg.get("premium_min_popularity_score", 1.1):
        return True
    genres = genre_names(event)
    return any(k.lower() in g for g in genres for k in cfg.get("premium_genre_keywords", []))


def budget_for(event, cfg):
    if is_premium(event, cfg):
        return cfg.get("premium_max_price", cfg["max_price"])
    return cfg["max_price"]


def check_event(event, prev, cfg):
    """Compare current prices against what we saw before.

    Returns (reasons_to_alert, new_state_for_this_event).
    """
    stats = event.get("stats", {}) or {}
    lowest = stats.get("lowest_price")
    median = stats.get("median_price")
    max_price = budget_for(event, cfg)
    drop = cfg["drop_alert_percent"] / 100.0

    # Show week: resale prices often fall fast right before the show,
    # so smaller drops count as news in the final days.
    days_left = days_until(event.get("datetime_utc"))
    final_window = days_left is not None and days_left <= cfg.get("final_days_before_show", 2)
    if final_window:
        drop = cfg.get("final_drop_alert_percent", 10) / 100.0

    state = dict(prev or {})
    state["title"] = event.get("title")
    state["date"] = event.get("datetime_utc")
    state["last_lowest"] = lowest
    state["last_median"] = median
    state["last_checked"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    reasons = []
    if lowest is None or median is None:
        return reasons, state  # no tickets listed right now

    # Price history for the dashboard's little price chart: add a point when the
    # price changes or every 6 hours, keeping the most recent 40 points.
    history = state.get("history", [])
    stamp = state["last_checked"]
    if (not history or history[-1][1] != lowest or history[-1][2] != median
            or stamp[:13] >= _hours_later(history[-1][0], 6)):
        history.append([stamp, lowest, median])
    state["history"] = history[-40:]

    # 1) "Good seats in budget": the median listing is at or under the budget,
    #    so a decent seat (not just the worst one) is likely affordable.
    if median <= max_price and not state.get("median_alerted"):
        reasons.append(f"Typical seat now {money(median)} (your budget is {money(max_price)})")
        state["median_alerted"] = True
    elif median > max_price * 1.05:
        state["median_alerted"] = False  # reset so a future dip alerts again

    # 2) "Price drop": cheapest ticket fell a lot since the last alert/first look.
    baseline = state.get("baseline_lowest")
    if baseline is None:
        state["baseline_lowest"] = lowest
    elif lowest <= max_price and lowest <= baseline * (1 - drop):
        pct = round((1 - lowest / baseline) * 100)
        prefix = "🔥 Last-minute drop! " if final_window else ""
        reasons.append(f"{prefix}Cheapest ticket dropped {pct}%: {money(baseline)} → {money(lowest)}")
        state["baseline_lowest"] = lowest

    return reasons, state


SENT_LOG = []  # alerts sent this run, newest first, for the dashboard's "Recent alerts"


def send_notification(topic, title, message, click_url=None, tags=None, dry_run=False):
    SENT_LOG.insert(0, {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "title": title, "body": message.split("\n")[0], "url": click_url})
    if dry_run:
        print(f"\n[DRY RUN] would notify: {title}\n{message}\n{click_url or ''}")
        return
    payload = {"topic": topic, "title": title, "message": message, "tags": tags or ["ticket"]}
    if click_url:
        payload["click"] = click_url
        payload["actions"] = [{"action": "view", "label": "Open tickets", "url": click_url}]
    req = urllib.request.Request(
        NTFY_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30):
        pass


# ---------------------------------------------------------------- Ticketmaster
#
# Ticketmaster shows face-value prices and on-sale / presale times, so it's
# used for "new show announced" and "tickets go on sale soon" alerts.
# Resale price drops still come from SeatGeek above.

TM_URL = "https://app.ticketmaster.com/discovery/v2/events.json"
SG_PERFORMERS_URL = "https://api.seatgeek.com/2/performers"
TM_JUNK_WORDS = ["parking", "upgrade", "package", "suite", "tailgate", "add-on", "voucher", "shuttle"]


def geohash(lat, lon, precision=9):
    """Encode a location the way Ticketmaster's geoPoint filter expects."""
    chars = "0123456789bcdefghjkmnpqrstuvwxyz"
    lat_range, lon_range = [-90.0, 90.0], [-180.0, 180.0]
    out, bits, bit_count, even = [], 0, 0, True
    while len(out) < precision:
        rng, val = (lon_range, lon) if even else (lat_range, lat)
        mid = (rng[0] + rng[1]) / 2
        if val >= mid:
            bits = (bits << 1) | 1
            rng[0] = mid
        else:
            bits <<= 1
            rng[1] = mid
        even = not even
        bit_count += 1
        if bit_count == 5:
            out.append(chars[bits])
            bits, bit_count = 0, 0
    return "".join(out)


def fetch_tm_events(api_key, city, classification, cfg):
    now = datetime.now(timezone.utc)
    until = now + timedelta(days=cfg["days_ahead"])
    found = []
    for page in range(5):  # Ticketmaster only allows the first 1,000 results
        params = {
            "apikey": api_key,
            "geoPoint": geohash(city["lat"], city["lon"]),
            "radius": cfg["radius_miles"],
            "unit": "miles",
            "countryCode": "US",
            "classificationName": classification,
            "startDateTime": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "endDateTime": until.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sort": "date,asc",
            "size": 200,
            "page": page,
        }
        data = http_get_json(TM_URL + "?" + urllib.parse.urlencode(params))
        found.extend((data.get("_embedded") or {}).get("events", []))
        total_pages = (data.get("page") or {}).get("totalPages", 1)
        time.sleep(0.3)  # stay under Ticketmaster's 5-requests-per-second limit
        if page + 1 >= total_pages:
            break
    return found


def tm_artist(event):
    attractions = (event.get("_embedded") or {}).get("attractions") or []
    return attractions[0].get("name") if attractions else event.get("name", "Event")


def tm_genre_text(event):
    parts = []
    for c in event.get("classifications") or []:
        for key in ("segment", "genre", "subGenre"):
            parts.append(((c.get(key) or {}).get("name") or "").lower())
    return " ".join(parts)


def tm_names(event):
    names = [event.get("name", "")]
    names += [a.get("name", "") for a in (event.get("_embedded") or {}).get("attractions") or []]
    return " ".join(names).lower()


def seatgeek_artist_score(name, client_id, cache):
    """Look up how popular an artist is on SeatGeek (0-1). Cached for 7 days."""
    key = name.lower().strip()
    hit = cache.get(key)
    if hit:
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(hit["checked"].replace("Z", "+00:00"))
            if age < timedelta(days=7):
                return hit["score"]
        except (KeyError, ValueError):
            pass
    score = 0.0
    try:
        params = {"client_id": client_id, "q": name, "per_page": 5}
        data = http_get_json(SG_PERFORMERS_URL + "?" + urllib.parse.urlencode(params))
        for p in data.get("performers", []):
            if (p.get("name") or "").lower().strip() == key:
                score = p.get("score") or 0.0
                break
        time.sleep(0.2)
    except urllib.error.URLError as e:
        print(f"  (couldn't look up popularity for {name}: {e})")
        return None  # unknown: try again next run, don't cache
    cache[key] = {"score": score, "checked": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    return score


def tm_wanted(event, cfg, client_id, score_cache):
    names = tm_names(event)
    if any(w in (event.get("name") or "").lower() for w in TM_JUNK_WORDS):
        return False, None
    status = ((event.get("dates") or {}).get("status") or {}).get("code", "")
    if status in ("cancelled", "canceled", "postponed"):
        return False, None
    if any(n.lower() in names for n in cfg.get("never_watch", []) if n.strip()):
        return False, None
    if any(n.lower() in names for n in cfg.get("always_watch", []) if n.strip()):
        return True, None
    genres = tm_genre_text(event)
    is_comedy = "comedy" in genres
    keywords = cfg["concert_genre_keywords"] + cfg.get("premium_genre_keywords", [])
    if not is_comedy and not any(k.lower() in genres for k in keywords):
        return False, None
    score = seatgeek_artist_score(tm_artist(event), client_id, score_cache)
    if score is None or score < cfg.get("ticketmaster_min_artist_score", 0.5):
        return False, score
    return True, score


def tm_budget(event, score, cfg):
    genres = tm_genre_text(event)
    if any(k.lower() in genres for k in cfg.get("premium_genre_keywords", [])):
        return cfg.get("premium_max_price", cfg["max_price"])
    if score is not None and score >= cfg.get("premium_min_popularity_score", 1.1):
        return cfg.get("premium_max_price", cfg["max_price"])
    return cfg["max_price"]


def local_time(utc_iso, cfg):
    """Turn Ticketmaster's UTC time into a friendly Central-time string."""
    if not utc_iso:
        return None
    try:
        dt = datetime.fromisoformat(utc_iso.replace("Z", "+00:00"))
    except ValueError:
        return utc_iso
    try:
        from zoneinfo import ZoneInfo
        dt = dt.astimezone(ZoneInfo(cfg.get("timezone", "America/Chicago")))
    except Exception:
        dt = dt.astimezone(timezone(timedelta(hours=-6)))
    return dt.strftime("%a %b %-d, %-I:%M %p")


def tm_sale_moments(event):
    """All upcoming moments tickets can be bought: presales and public sale."""
    sales = event.get("sales") or {}
    moments = []
    for p in sales.get("presales") or []:
        if p.get("startDateTime"):
            moments.append((p["startDateTime"], p.get("name") or "Presale"))
    public = (sales.get("public") or {}).get("startDateTime")
    if public and not (sales.get("public") or {}).get("startTBD"):
        moments.append((public, "Public on-sale"))
    return sorted(moments)


def has_presale_access(presale_name, cfg):
    """True if a presale's name mentions a card, carrier or club Ben has (config: presale_access)."""
    name = (presale_name or "").lower()
    return any(k.lower() in name for k in cfg.get("presale_access", []) if k.strip())


def tm_describe(event, budget, cfg):
    venues = (event.get("_embedded") or {}).get("venues") or [{}]
    venue = venues[0]
    start = (event.get("dates") or {}).get("start") or {}
    when = nice_date(f"{start.get('localDate')}T{start.get('localTime') or '20:00:00'}")
    lines = [f"{venue.get('name', 'Unknown venue')}, {(venue.get('city') or {}).get('name', '')}", when]
    prices = event.get("priceRanges") or []
    if prices:
        lo = min(p.get("min") or 0 for p in prices)
        hi = max(p.get("max") or 0 for p in prices)
        note = " ✅ within your budget" if lo and lo <= budget else ""
        lines.append(f"Face value {money(lo)}–{money(hi)}{note}")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    upcoming = [(t, n) for t, n in tm_sale_moments(event) if t > now]
    for t, n in upcoming[:4]:
        star = " ⭐ you have access" if has_presale_access(n, cfg) else ""
        lines.append(f"{n}: {local_time(t, cfg)}{star}")
    if not upcoming:
        lines.append("On sale now")
    return "\n".join(lines)


def check_tm_event(event, prev, budget, cfg):
    """Return (alerts, new_state). Alerts: new show, and sale-starting-soon reminders."""
    now = datetime.now(timezone.utc)
    now_s = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    soon_s = (now + timedelta(hours=cfg.get("onsale_reminder_hours", 24))).strftime("%Y-%m-%dT%H:%M:%SZ")
    state = dict(prev or {})
    state["title"] = event.get("name")
    state["date"] = ((event.get("dates") or {}).get("start") or {}).get("dateTime")
    reminded = set(state.get("reminded", []))
    alerts = []

    if prev is None:
        alerts.append(("📣 New show", tm_describe(event, budget, cfg)))
        # A new show whose sale starts within the window doesn't need a second ping.
        for t, _ in tm_sale_moments(event):
            if now_s < t <= soon_s:
                reminded.add(t)
    else:
        for t, name in tm_sale_moments(event):
            if now_s < t <= soon_s and t not in reminded:
                hours = max(1, round((datetime.fromisoformat(t.replace("Z", "+00:00")) - now).total_seconds() / 3600))
                star = "⭐ " if has_presale_access(name, cfg) else ""
                alerts.append((f"⏰ {star}{name} in {hours}h", tm_describe(event, budget, cfg)))
                reminded.add(t)
                break  # one reminder at a time is plenty
    state["reminded"] = sorted(reminded)
    return alerts, state


def run_ticketmaster(cfg, state, client_id, tm_key, first_run, fetch_tm=fetch_tm_events):
    """Returns (list of alerts, updated tm state, count watched)."""
    tm_state = state.get("tm_events", {})
    score_cache = state.setdefault("artist_scores", {})
    seen = {}
    for city in cfg["cities"]:
        for classification in cfg.get("ticketmaster_classifications", ["Pop", "Comedy"]):
            try:
                events = fetch_tm(tm_key, city, classification, cfg)
            except urllib.error.HTTPError as e:
                print(f"Ticketmaster said {e.code} for {city['name']}/{classification}. "
                      "A 401 means the Ticketmaster key is wrong. Skipping Ticketmaster this run.")
                return [], state.get("tm_events"), 0, [], {}
            for ev in events:
                if ev.get("id") in seen:
                    continue
                ok, score = tm_wanted(ev, cfg, client_id, score_cache)
                if ok:
                    seen[ev["id"]] = (ev, score)
    print(f"Ticketmaster: watching {len(seen)} shows.")

    alerts = []
    new_state = {}
    upcoming_sales = []
    faces = {}  # artist+date -> Ticketmaster face value, to fill in SeatGeek shows without prices
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for event_id, (ev, score) in seen.items():
        budget = tm_budget(ev, score, cfg)
        ev_alerts, ev_state = check_tm_event(ev, tm_state.get(event_id), budget, cfg)
        new_state[event_id] = ev_state
        upcoming_sales.extend(tm_dashboard_items(ev, budget, now_iso, cfg))
        prices = ev.get("priceRanges") or []
        start = (ev.get("dates") or {}).get("start") or {}
        if start.get("localDate"):
            key = f"{tm_artist(ev).lower().strip()}|{start['localDate']}"
            faces[key] = {
                "min": min((p.get("min") or 0) for p in prices) if prices else None,
                "max": max((p.get("max") or 0) for p in prices) if prices else None,
                "url": ev.get("url"),
            }
        if not first_run:
            for title, body in ev_alerts:
                alerts.append((f"{title}: {tm_artist(ev)}", body, ev.get("url")))

    # Remember shows we didn't see this run until their date passes,
    # so a show that briefly drops out of results isn't announced as "new" again.
    now_s = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for event_id, old in tm_state.items():
        if event_id not in new_state and (old.get("date") or "9999") > now_s:
            new_state[event_id] = old
    return alerts, new_state, len(seen), upcoming_sales, faces


def tm_dashboard_items(ev, budget, now_iso, cfg):
    """The next sale moment for a show, for the dashboard's "On sale soon" list."""
    upcoming = [(t, n) for t, n in tm_sale_moments(ev) if t > now_iso]
    if not upcoming:
        return []
    t, name = upcoming[0]
    venue = ((ev.get("_embedded") or {}).get("venues") or [{}])[0]
    start = (ev.get("dates") or {}).get("start") or {}
    prices = ev.get("priceRanges") or []
    return [{
        "artist": tm_artist(ev),
        "venue": venue.get("name", ""),
        "city": (venue.get("city") or {}).get("name", ""),
        "date": f"{start.get('localDate')}T{start.get('localTime') or '20:00:00'}",
        "sale_name": name,
        "sale_at": t,
        "has_access": has_presale_access(name, cfg),
        "face_min": min((p.get("min") or 0) for p in prices) if prices else None,
        "face_max": max((p.get("max") or 0) for p in prices) if prices else None,
        "budget": budget,
        "url": ev.get("url"),
        "comedy": "comedy" in tm_genre_text(ev),
    }]


# ---------------------------------------------------------------- yearly reminders
#
# For deals no ticket API shows (like Live Nation's yearly $30 ticket sale),
# the bot sends a heads-up on a set date each year (config: yearly_reminders).

def send_yearly_reminders(cfg, already_sent, topic, dry_run):
    try:
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo(cfg.get("timezone", "America/Chicago"))).date()
    except Exception:
        today = (datetime.now(timezone.utc) - timedelta(hours=6)).date()
    sent = [s for s in already_sent if s[:4] >= str(today.year - 1)]  # forget old years
    for r in cfg.get("yearly_reminders", []):
        try:
            due = today.replace(month=int(r["month"]), day=int(r["day"]))
        except (KeyError, ValueError):
            print(f"Skipping a yearly reminder with a bad month/day: {r}")
            continue
        key = f"{today.year}:{r.get('title', '')}"
        # Send on the date, or within a week after if the bot was paused that day.
        if due <= today <= due + timedelta(days=7) and key not in sent:
            send_notification(topic, r.get("title", "Reminder"), r.get("message", ""),
                              click_url=r.get("url"), tags=["calendar"], dry_run=dry_run)
            print(f"Sent yearly reminder: {r.get('title')}")
            sent.append(key)
    return sent


# ---------------------------------------------------------------- dashboard
#
# Each run writes site/index.html: dashboard_template.html with the latest data
# baked in. The GitHub workflow then publishes that folder with GitHub Pages.

SITE_DIR = os.path.join(HERE, "site")
TEMPLATE_PATH = os.path.join(HERE, "dashboard_template.html")


def write_dashboard(cfg, seen, events_state, tm_sales, alert_log, tm_enabled, tm_faces=None):
    tm_faces = tm_faces or {}
    shows = []
    for event_id, (ev, city_name) in seen.items():
        stats = ev.get("stats") or {}
        venue = ev.get("venue") or {}
        budget = budget_for(ev, cfg)
        median = stats.get("median_price")
        days_left = days_until(ev.get("datetime_utc"))
        hist = (events_state.get(event_id) or {}).get("history", [])
        shows.append({
            "id": event_id,
            "artist": short_title(ev),
            "title": ev.get("title"),
            "venue": venue.get("name", ""),
            "city": venue.get("city") or city_name,
            "area": city_name,
            "date": ev.get("datetime_local"),
            "lowest": stats.get("lowest_price"),
            "median": median,
            "listings": stats.get("listing_count") or 0,
            "budget": budget,
            "big_act": is_premium(ev, cfg),
            "deal": median is not None and median <= budget,
            "last_minute": days_left is not None and days_left <= cfg.get("final_days_before_show", 2),
            "comedy": any((t.get("name") or "") == "comedy" for t in ev.get("taxonomies") or [])
                      or "comedy" in " ".join(genre_names(ev)),
            "history": [h[1] for h in hist if h[1] is not None],
            "url": ev.get("url"),
            "face": tm_faces.get(f"{short_title(ev).lower().strip()}|{str(ev.get('datetime_local'))[:10]}"),
        })
    data = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cities": [c["name"] for c in cfg["cities"]],
        "budget": cfg["max_price"],
        "big_budget": cfg.get("premium_max_price", cfg["max_price"]),
        "shows": shows,
        "prices_available": any(s["median"] is not None or s["lowest"] is not None for s in shows),
        "sales": sorted(tm_sales, key=lambda s: s["sale_at"]),
        "alerts": alert_log,
        "ticketmaster": tm_enabled,
    }
    try:
        with open(TEMPLATE_PATH, encoding="utf-8") as f:
            template = f.read()
    except FileNotFoundError:
        print("dashboard_template.html not found, skipping the dashboard.")
        return
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    os.makedirs(SITE_DIR, exist_ok=True)
    with open(os.path.join(SITE_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(template.replace("__ENCORE_DATA__", payload))
    # The home-screen icon is built into this file, so there's no picture to upload.
    with open(os.path.join(SITE_DIR, "icon.png"), "wb") as dst:
        dst.write(base64.b64decode("".join(ICON_PNG_BASE64)))
    print(f"Dashboard written: {len(shows)} shows, {len(tm_sales)} upcoming sales.")


# Encore's home-screen icon (a 180x180 PNG), stored as text.
ICON_PNG_BASE64 = (
    "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"
    "AAAAAElFTkSuQmCC"
)


# ---------------------------------------------------------------- main

def run(dry_run=False, fetch=fetch_events, fetch_tm=fetch_tm_events):
    cfg = load_json(CONFIG_PATH, None)
    if cfg is None:
        sys.exit("config.json is missing - it must sit next to ticket_bot.py")

    client_id = os.environ.get("SEATGEEK_CLIENT_ID", "").strip()
    tm_key = os.environ.get("TICKETMASTER_API_KEY", "").strip()
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not client_id and fetch is fetch_events:
        sys.exit("SEATGEEK_CLIENT_ID is not set (add it as a GitHub secret)")
    if not topic and not dry_run:
        sys.exit("NTFY_TOPIC is not set (add it as a GitHub secret)")

    state = load_json(STATE_PATH, {"events": {}})
    first_run = "last_run" not in state
    tm_first_run = "tm_events" not in state

    # Gather events, de-duplicated by SeatGeek event id.
    seen = {}
    for city in cfg["cities"]:
        for taxonomy in cfg["categories"]:
            try:
                events = fetch(client_id, city, taxonomy, cfg)
            except urllib.error.HTTPError as e:
                sys.exit(f"SeatGeek said {e.code} for {city['name']}/{taxonomy}. "
                         "A 401 or 403 usually means the client ID is wrong.")
            for ev in events:
                if wanted(ev, taxonomy, cfg):
                    seen.setdefault(str(ev["id"]), (ev, city["name"]))

    print(f"Watching {len(seen)} events across {', '.join(c['name'] for c in cfg['cities'])}.")

    alerts = []
    new_events_state = {}
    for event_id, (ev, city_name) in seen.items():
        reasons, ev_state = check_event(ev, state["events"].get(event_id), cfg)
        new_events_state[event_id] = ev_state
        if reasons:
            alerts.append((ev, city_name, reasons))

    # Ticketmaster is optional: it only runs if its key has been added.
    tm_alerts, tm_state, tm_count, tm_sales, tm_faces = [], state.get("tm_events"), 0, [], {}
    if tm_key:
        tm_alerts, tm_state, tm_count, tm_sales, tm_faces = run_ticketmaster(cfg, state, client_id, tm_key, tm_first_run, fetch_tm)
    else:
        print("Ticketmaster: no TICKETMASTER_API_KEY set, skipping.")

    if tm_key and tm_first_run and not first_run:
        send_notification(topic, "🎟️ Ticketmaster added",
                          f"Now also watching {tm_count} Ticketmaster shows for new announcements "
                          "and on-sale reminders.", tags=["tada"], dry_run=dry_run)

    limit = cfg.get("max_alerts_per_run", 8)
    for title, body, url in tm_alerts[:limit]:
        send_notification(topic, title, body, click_url=url, dry_run=dry_run)
        print(f"Alerted: {title}")
    if len(tm_alerts) > limit:
        send_notification(topic, "📣 More Ticketmaster news",
                          f"{len(tm_alerts) - limit} more new shows or on-sales this hour. "
                          "Raise max_alerts_per_run in config.json to see them all.", dry_run=dry_run)

    if first_run:
        # Don't blast dozens of alerts on day one: send one summary instead.
        in_budget = sorted(
            (a for a in alerts),
            key=lambda a: (a[0].get("stats", {}) or {}).get("median_price") or 1e9,
        )
        lines = [f"• {short_title(ev)} ({city}) – typical {money((ev.get('stats') or {}).get('median_price'))}"
                 for ev, city, _ in in_budget[:8]]
        premium = sum(1 for ev, _ in seen.values() if is_premium(ev, cfg))
        body = (f"Now watching {len(seen)} popular events ({premium} get the "
                f"{money(cfg.get('premium_max_price', cfg['max_price']))} big-act budget). "
                f"{len(in_budget)} already have typical seats within budget.")
        if tm_key:
            body += f" Also watching {tm_count} Ticketmaster shows for new announcements and on-sales."
        if lines:
            body += "\n" + "\n".join(lines)
        send_notification(topic, "🎟️ Encore is running", body, tags=["tada"], dry_run=dry_run)
        print(body)
    else:
        limit = cfg.get("max_alerts_per_run", 8)
        for ev, city_name, reasons in alerts[:limit]:
            icon = "🔥" if any(r.startswith("🔥") for r in reasons) else "🎟️"
            send_notification(
                topic,
                f"{icon} {short_title(ev)}",
                "\n".join(reasons) + "\n" + describe(ev, city_name),
                click_url=ev.get("url"),
                dry_run=dry_run,
            )
            print(f"Alerted: {ev.get('title')} - {'; '.join(reasons)}")
        if len(alerts) > limit:
            send_notification(topic, "🎟️ More deals",
                              f"{len(alerts) - limit} more events hit your alerts this hour. "
                              "Raise max_alerts_per_run in config.json to see them all.",
                              dry_run=dry_run)
        if not alerts:
            print("No new deals this run.")

    yearly_sent = send_yearly_reminders(cfg, state.get("yearly_sent", []), topic, dry_run)

    alert_log = (SENT_LOG + state.get("alert_log", []))[:30]
    write_dashboard(cfg, seen, new_events_state, tm_sales, alert_log, tm_enabled=bool(tm_key), tm_faces=tm_faces)

    # Keep history only for events still upcoming (drops past shows automatically).
    if not dry_run:
        new_state = {"events": new_events_state,
                     "artist_scores": state.get("artist_scores", {}),
                     "yearly_sent": yearly_sent,
                     "alert_log": alert_log,
                     "last_run": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        if tm_state is not None:
            new_state["tm_events"] = tm_state
        save_json(STATE_PATH, new_state)


def main():
    args = set(sys.argv[1:])
    if "--test-notify" in args:
        topic = os.environ.get("NTFY_TOPIC", "").strip()
        if not topic:
            sys.exit("NTFY_TOPIC is not set (add it as a GitHub secret)")
        send_notification(topic, "🎟️ Test from Encore",
                          "If you can read this on your phone, notifications work!", tags=["white_check_mark"])
        print("Test notification sent.")
        return
    run(dry_run="--dry-run" in args)


if __name__ == "__main__":
    main()
