import time
import requests
from bs4 import BeautifulSoup

URL = "https://secure.onreg.com/onreg2/bibexchange/?eventid=7143&language=us"
NTFY_TOPIC = "leon-bib-7143-xk92"  # ← your topic name here
CHECK_INTERVAL = 20  # seconds

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; BibMonitor/1.0)"}

def check_for_bibs():
    try:
        r = requests.get(URL, headers=HEADERS, timeout=10)
        text = r.text.lower()
        no_bibs = "no bib" in text or "no entries" in text or "sold out" in text
        return not no_bibs
    except Exception as e:
        print(f"[Error] {e}")
        return False

def send_alert():
    print("🚨 BIB FOUND — sending alert!")
    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data="BIB IS AVAILABLE — BUY NOW",
        headers={
            "Title": "Race Bib Alert 🚨",
            "Priority": "urgent",
            "Tags": "rotating_light",
            "Click": URL
        }
    )

def main():
    print("Monitor started...")
    while True:
        available = check_for_bibs()
        ts = time.strftime("%H:%M:%S")
        if available:
            send_alert()
            time.sleep(60)  # re-alert every 60s until you buy
        else:
            print(f"[{ts}] No bibs yet")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
