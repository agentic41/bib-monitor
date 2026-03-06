import time
import requests
from bs4 import BeautifulSoup
import sys

NTFY_TOPIC = "leon-bib-7143-xk92"
CHECK_INTERVAL = 10
BOOKED_COOLDOWN = 300  # 5 min cooldown if all tickets are booked/in progress

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; BibMonitor/1.0)"}

SOURCES = [
    {
        "name": "OnReg",
        "url": "https://secure.onreg.com/onreg2/bibexchange/?eventid=7143&language=us",
        "no_bib_phrases": ["no bib", "no entries", "sold out"],
        "booked_cooldown_until": 0
    },
    {
        "name": "SportsTiming",
        "url": "https://www.sportstiming.dk/event/17008/resale?subid=77089&subhash=638949451700000000&distance=97759",
        "no_bib_phrases": ["no bib", "no entries", "sold out", "ingen", "udsolgt", "no race numbers for sale", "there are no tickets for sale"],
        "booked_cooldown_until": 0
    }
]

def check_source(source):
    if time.time() < source["booked_cooldown_until"]:
        remaining = int(source["booked_cooldown_until"] - time.time())
        print(f"[{time.strftime('%H:%M:%S')}] {source['name']}: Skipping ({remaining}s cooldown)", flush=True)
        return False

    try:
        r = requests.get(source["url"], headers=HEADERS, timeout=10)
        text = r.text.lower()

        # No tickets at all
        no_bibs = any(phrase in text for phrase in source["no_bib_phrases"])
        if no_bibs:
            return False

        # Tickets exist — check if all are taken
        has_tickets = (
            "tickets for sale" in text or
            "race numbers for sale" in text or
            "bib" in text
        )

        if has_tickets:
            has_booked = "booked" in text
            has_in_progress = "in progress" in text

            # If every ticket is either booked or in progress — not worth alerting
            if has_booked or has_in_progress:
                source["booked_cooldown_until"] = time.time() + BOOKED_COOLDOWN
                print(f"[{time.strftime('%H:%M:%S')}] {source['name']}: Tickets exist but all booked/in progress — cooling down {BOOKED_COOLDOWN}s", flush=True)
                return False

        return True

    except Exception as e:
        print(f"[Error] {source['name']}: {e}", flush=True)
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
    print("Monitor started — watching 2 sources...", flush=True)
    while True:
        for source in SOURCES:
            available = check_source(source)
            ts = time.strftime("%H:%M:%S")
            if available:
                send_alert(source)
            else:
                print(f"[{ts}] {source['name']}: No bibs yet", flush=True)
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()