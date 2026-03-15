import csv
import os
import time
import datetime
import requests

NTFY_TOPIC = "leon-bib-7143-xk92"
CHECK_INTERVAL = 10
BOOKED_COOLDOWN = 300
LOG_DIR = os.environ.get("LOG_DIR", "logs")

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
        "name": "SportsTiming",
        "url": "https://www.sportstiming.dk/event/17008/resale?distance=97759",
        "no_bib_phrases": ["no bib", "no entries", "sold out", "ingen", "udsolgt", "no race numbers for sale", "there are no tickets for sale"],
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
    source["last_state"] = last_state
    print(f"[Log] {source['name']}: restored last state = {last_state}", flush=True)

def log_event(source, prev_state, new_state):
    now = datetime.datetime.now()
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

def get_state(source):
    try:
        r = requests.get(source["url"], headers=HEADERS, timeout=10)
        text = r.text.lower()

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
        has_price = "dkk" in text or "kr." in text or "price" in text

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
        for source in SOURCES:
            should_alert = check_source(source)
            if should_alert:
                send_alert(source)
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
