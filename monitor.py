import time
import requests
from bs4 import BeautifulSoup

NTFY_TOPIC = "leon-bib-7143-xk92"
CHECK_INTERVAL = 20

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; BibMonitor/1.0)"}

SOURCES = [
    {
        "name": "OnReg",
        "url": "https://secure.onreg.com/onreg2/bibexchange/?eventid=7143&language=us",
        "no_bib_phrases": ["no bib", "no entries", "sold out"]
    },
    {
        "name": "SportsTiming",
        "url": "https://www.sportstiming.dk/event/17008/resale?subid=77089&subhash=638949451700000000&distance=97759",
        "no_bib_phrases": ["no bib", "no entries", "sold out", "ingen", "udsolgt"]  # Danish too
    }
]

def check_source(source):
    try:
        r = requests.get(source["url"], headers=HEADERS, timeout=10)
        text = r.text.lower()
        no_bibs = any(phrase in text for phrase in source["no_bib_phrases"])
        return not no_bibs
    except Exception as e:
        print(f"[Error] {source['name']}: {e}")
        return False

def send_alert(source):
    print(f"BIB FOUND on {source['name']}!")
    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=f"BIB AVAILABLE on {source['name']} - BUY NOW".encode("utf-8"),
        headers={
            "Title": f"Race Bib Alert ({source['name']})",
            "Priority": "urgent",
            "Tags": "rotating_light",
            "Click": source["url"]
        }
    )

def main():
    print("Monitor started — watching 2 sources...")
    while True:
        for source in SOURCES:
            available = check_source(source)
            ts = time.strftime("%H:%M:%S")
            if available:
                send_alert(source)
            else:
                print(f"[{ts}] {source['name']}: No bibs yet")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()