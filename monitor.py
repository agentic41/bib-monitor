import csv
import os
import time
import datetime
from zoneinfo import ZoneInfo
import requests

_TZ = ZoneInfo("Europe/Copenhagen")

NTFY_TOPIC = "leon-bib-7143-xk92"
CHECK_INTERVAL = 10
BOOKED_COOLDOWN = 300
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.environ.get("LOG_DIR", os.path.join(_SCRIPT_DIR, "logs"))

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; BibMonitor/1.0)"}

SOURCES = [
     {
        "name": "OnReg",
        "url": "https://secure.onreg.com/onreg2/bibexchange/?eventid=7143&language=us",
        "no_bib_phrases": ["no bib", "no entries", "sold out"],
        "booked_cooldown_until": 0,
        "last_state": "empty"
    },
    {
        "name": "SportsTiming10k",
        "url": "https://www.sportstiming.dk/event/17008/resale",
        "no_bib_phrases": ["no bib", "no entries", "sold out", "ingen billetter til salg", "Der findes ingen billetter til salg", "ingen startnumre til salg", "udsolgt", "no race numbers for sale", "there are no tickets for sale"],
        "filter_distance": "10 km - kbh",
        "booked_cooldown_until": 0,
        "last_state": "empty"
    },
   {
        "name": "SportsTiming5k",
        "url": "https://www.sportstiming.dk/event/17008/resale",
        "no_bib_phrases": ["no bib", "no entries", "sold out", "ingen billetter til salg", "Der findes ingen billetter til salg", "ingen startnumre til salg", "udsolgt", "no race numbers for sale", "there are no tickets for sale"],
        "filter_distance": "5 km - kbh",
        "booked_cooldown_until": 0,
        "last_state": "empty"
    },
    {
        "name": "AarhusMotion",
        "url": "https://www.aarhusmotion.dk/event/293/resale",
        "no_bib_phrases": ["no bib", "no entries", "sold out", "ingen billetter til salg", "ingen startnumre til salg", "udsolgt", "no race numbers for sale", "there are no tickets for sale"],
        "booked_cooldown_until": 0,
        "last_state": "empty"
    }
]

LOG_FIELDS = ["iso_datetime", "date", "weekday", "hour", "minute", "event", "prev_state", "new_state"]

def get_log_path(source):
    os.makedirs(LOG_DIR, exist_ok=True)
    safe_name = source["name"].replace(" ", "_")
    return os.path.join(LOG_DIR, f"{safe_name}_events.csv")

def init_log(source):
    path = get_log_path(source)
    if not os.path.exists(path):
        with open(path, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=LOG_FIELDS).writeheader()
        print(f"[Log] Created {path}", flush=True)

def load_last_state(source):
    path = get_log_path(source)
    last_state = "empty"
    try:
        with open(path, "r", newline="") as f:
            rows = list(csv.DictReader(f))
            if rows:
                last_state = rows[-1]["new_state"]
    except FileNotFoundError:
        pass
    # Treat transient states as empty on startup — we don't know if tickets are
    # still there after a restart, and "in_progress"/"available" as prev would
    # suppress alerts on the next appearance.
    if last_state in ("in_progress", "available"):
        last_state = "empty"
    source["last_state"] = last_state
    print(f"[Log] {source['name']}: restored last state = {last_state}", flush=True)

def log_event(source, prev_state, new_state):
    now = datetime.datetime.now(tz=_TZ)
    event = _classify_event(prev_state, new_state)
    row = {
        "iso_datetime": now.isoformat(timespec="seconds"),
        "date":         now.strftime("%Y-%m-%d"),
        "weekday":      now.strftime("%A"),
        "hour":         now.hour,
        "minute":       now.minute,
        "event":        event,
        "prev_state":   prev_state,
        "new_state":    new_state,
    }
    with open(get_log_path(source), "a", newline="") as f:
        csv.DictWriter(f, fieldnames=LOG_FIELDS).writerow(row)
    print(f"[Log] {source['name']}: {prev_state} → {new_state} ({event})", flush=True)

def _classify_event(prev, new):
    if prev in ("empty", "booked") and new in ("available", "in_progress"):
        return "appeared"
    if prev in ("available", "in_progress") and new == "empty":
        return "gone"
    if new == "booked":
        return "booked"
    if new == "in_progress":
        return "in_progress"
    return "changed"

_url_cache = {}  # per-cycle cache: url → response text

def get_state(source):
    try:
        url = source["url"]
        if url in _url_cache:
            raw = _url_cache[url]
        else:
            raw = requests.get(url, headers=HEADERS, timeout=10).text
            _url_cache[url] = raw
        text = raw.lower()

        if "easy, tiger" in text or "refreshing the page a bit too often" in text:
            print(f"[RateLimit] {source['name']}: holding last state", flush=True)
            return source["last_state"]

        # If a distance filter is set, only look at table rows for that distance.
        # The server may return all distances regardless of the query param, so we
        # narrow the text to rows that mention the target distance label.
        filter_distance = source.get("filter_distance")
        if filter_distance:
            # Extract table rows (<tr>...</tr>) that contain the distance label.
            # When no tickets exist the page has no <tr> at all, so 0 rows = empty.
            import re as _re
            all_rows = _re.findall(r"<tr>.*?</tr>", text, _re.DOTALL)
            matching = [row for row in all_rows if filter_distance in row]
            if not matching:
                return "empty"
            # Rows found — tickets exist for this distance.
            # SportsTiming uses "køb" (buy) for purchasable and "reserveret" for
            # tickets locked in someone else's checkout.
            row_text = " ".join(matching)
            has_price = "dkk" in row_text or " kr" in row_text
            if not has_price:
                return "empty"
            # "Køb" is rendered as HTML entity K&#248;b — check both forms.
            # Check buyable BEFORE reserveret: a mix means at least one is purchasable.
            if "køb" in row_text or "k&#248;b" in row_text:
                return "available"
            if "reserveret" in row_text:
                # "Reserveret" = locked in someone's checkout, NOT a completed purchase.
                # Treat as in_progress (no cooldown) so we keep checking every 10s.
                return "in_progress"
            return "available"

        no_bibs = any(phrase in text for phrase in source["no_bib_phrases"])
        if no_bibs:
            return "empty"

        has_tickets = (
            "tickets for sale" in text or
            "race numbers for sale" in text or
            "bib" in text or
            "tickets have been resold" in text or
            "startnummer" in text
        )
        if not has_tickets:
            return "empty"

        # Only trust "in progress" / "booked" if there's also a price on the page
        # meaning a real ticket row exists
        has_price = "dkk" in text or " kr" in text or "kr." in text or "price" in text

        if not has_price:
            return "empty"

        if "booked" in text and "in progress" not in text:
            return "booked"
        if "in progress" in text:
            return "in_progress"

        return "available"

    except Exception as e:
        print(f"[Error] {source['name']}: {e}", flush=True)
        return source["last_state"]

def check_source(source):
    if time.time() < source["booked_cooldown_until"]:
        remaining = int(source["booked_cooldown_until"] - time.time())
        print(f"[{time.strftime('%H:%M:%S')}] {source['name']}: Skipping ({remaining}s cooldown)", flush=True)
        return False
    state = get_state(source)
    ts = time.strftime("%H:%M:%S")
    prev = source["last_state"]
    source["last_state"] = state
    print(f"[{ts}] {source['name']}: {state}", flush=True)

    if state != prev:
        log_event(source, prev, state)

    if state == "booked":
        source["booked_cooldown_until"] = time.time() + BOOKED_COOLDOWN
        return False
    if state == "empty":
        return False
    if state in ("available", "in_progress") and prev in ("empty", "booked"):
        return True
    return False

def send_alert(source):
    print(f"BIB FOUND on {source['name']}!", flush=True)
    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=f"BIB AVAILABLE on {source['name']} - BUY NOW".encode("utf-8"),
        headers={
            "Title": f"Race Bib Alert ({source['name']})",
            "Priority": "urgent",
            "Tags": "rotating_light",
            "Click": source["url"],
            "Actions": f"view, Open {source['name']}, {source['url']}"
        }
    )

def main():
    for source in SOURCES:
        init_log(source)
        load_last_state(source)
    print(f"Monitor started — watching {len(SOURCES)} source(s)...", flush=True)
    while True:
        _url_cache.clear()
        for source in SOURCES:
            should_alert = check_source(source)
            if should_alert:
                send_alert(source)
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
