import requests
import trafilatura
from datetime import datetime, timedelta
import pytz
import time
import json
import os
from dotenv import load_dotenv
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

load_dotenv()

# -----------------------
# Configuration
# -----------------------
BASE_KEYWORDS = [
    "regulation", "compliance"
    # Add more later if needed
]
NEW_MEMBER_EXTRA_KEYWORDS = [
    "fraud", "case"
]
KEYWORDS_NEW_MEMBER = BASE_KEYWORDS + NEW_MEMBER_EXTRA_KEYWORDS

SERP_API_KEYS = [
    os.getenv("SERPAPI_KEY1"),
    os.getenv("SERPAPI_KEY2"),
    os.getenv("SERPAPI_KEY3"),
    os.getenv("SERPAPI_KEY4"),
    os.getenv("SERPAPI_KEY5")
]

DIFFBOT_KEYS = [
    os.getenv("DIFFBOT_TOKEN1"),
    os.getenv("DIFFBOT_TOKEN2"),
    os.getenv("DIFFBOT_TOKEN3")
]

# -----------------------
# Helper: Fetch content
# -----------------------
def fetch_article_content(url):
    try:
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            return trafilatura.extract(downloaded)
        return None
    except Exception as e:
        print(f"[Content Fetch Error] {e} for URL: {url}")
        return None


def fetch_diffbot_content(url, token, max_retries=3, sleep_seconds=5):
    for attempt in range(max_retries):
        try:
            api_url = f"https://api.diffbot.com/v3/article?url={url}&token={token}"
            response = requests.get(api_url, timeout=15)
            data = response.json()
            if "objects" not in data or not data["objects"]:
                return None
            article = data["objects"][0]
            return {
                "headline": article.get("title"),
                "author": article.get("author"),
                "site_name": article.get("siteName"),
                "content": article.get("text"),
                "url": article.get("pageUrl"),
            }
        except Exception as e:
            print(f"[Diffbot Error] Attempt {attempt + 1}: {e}")
            time.sleep(sleep_seconds)
    return None


# -----------------------
# Fetch SerpAPI News with Custom Date & Time Filtering
# -----------------------
def fetch_serpapi_news(
    query,
    serp_keys,
    diffbot_keys,
    time_filter_mode="today_7_to_10",  # or "yesterday_7am_to_7pm" or None (all today)
    max_retries=3,
    sleep_seconds=5,
):
    ist = pytz.timezone("Asia/Kolkata")
    results = []
    serp_index = 0
    diffbot_index = 0

    url = "https://serpapi.com/search"
    
    # Base query with sites
    params_base = {
        "engine": "google_news",
        "q": (
            "site:economictimes.indiatimes.com "
            "OR site:business-standard.com "
            "OR site:financialexpress.com "
            f"{query}"
        ),
        "hl": "en",
        "gl": "in",
    }

    # Set date range based on mode
    if time_filter_mode == "today_7_to_10":
        params_base["tbs"] = "qdr:d"  # today only
    elif time_filter_mode == "yesterday_7am_to_7pm":
        # SerpAPI qdr:d = past 24 hours → we will filter manually below
        params_base["tbs"] = "qdr:d2"  # past 2 days to be safe
    else:
        params_base["tbs"] = "qdr:d"

    for attempt in range(max_retries):
        serp_key = serp_keys[serp_index % len(serp_keys)]
        params = {**params_base, "api_key": serp_key}

        try:
            response = requests.get(url, params=params, timeout=20)
            data = response.json()

            if "news_results" not in data:
                print("[SerpAPI] No news_results in response")
                break

            for item in data["news_results"]:
                link = item.get("link")
                title = item.get("title")
                source_name = item.get("source", {}).get("name")
                date_str = item.get("date")

                if not link or not date_str:
                    continue

                # Parse published date
                try:
                    # Format: "12/08/2025, 03:30 pm, +0000 UTC" or similar
                    pub_dt = datetime.strptime(date_str.split(", +0000 UTC")[0], "%m/%d/%Y, %I:%M %p")
                    pub_dt = pub_dt.replace(tzinfo=pytz.UTC).astimezone(ist)
                except Exception as e:
                    print(f"[Date Parse Error] {date_str} -> {e}")
                    continue

                now_ist = datetime.now(ist)

                # === Time Filtering Logic ===
                if time_filter_mode == "today_7_to_10":
                    if pub_dt.date() != now_ist.date():
                        continue
                    if not (7 <= pub_dt.hour < 10):
                        continue

                elif time_filter_mode == "yesterday_7am_to_7pm":
                    yesterday = (now_ist - timedelta(days=1)).date()
                    if pub_dt.date() != yesterday:
                        continue
                    if not (7 <= pub_dt.hour < 19):  # 7 AM to 7 PM
                        continue

                # === Fetch Content ===
                content = fetch_article_content(link)
                if not content:
                    diff_token = diffbot_keys[diffbot_index % len(diffbot_keys)]
                    diffbot_index += 1
                    diff_data = fetch_diffbot_content(link, diff_token)
                    if diff_data:
                        results.append(diff_data)
                        time.sleep(sleep_seconds)
                        continue
                    else:
                        continue  # skip if both fail

                results.append({
                    "headline": title,
                    "author": None,
                    "site_name": source_name,
                    "content": content,
                    "url": link,
                    "published_at": pub_dt.strftime("%Y-%m-%d %H:%M IST")
                })

            break  # success

        except Exception as e:
            print(f"[SerpAPI Error {attempt+1}] {e}")
            serp_index += 1
            time.sleep(sleep_seconds)

    return results


# -----------------------
# Fetch for keyword pairs
# -----------------------
def fetch_news_for_keywords(keywords, time_filter_mode):
    all_results = {}
    for i in range(0, len(keywords) - 1, 2):
        k1 = keywords[i]
        k2 = keywords[i + 1]
        query = f"{k1} OR {k2}"
        print(f"\nFetching news for: {k1}, {k2} | Mode: {time_filter_mode}")
        
        articles = fetch_serpapi_news(
            query=query,
            serp_keys=SERP_API_KEYS,
            diffbot_keys=DIFFBOT_KEYS,
            time_filter_mode=time_filter_mode,
        )
        
        all_results[f"{k1}_{k2}"] = articles
        time.sleep(10)  # Avoid rate limits

    return all_results


# -----------------------
# Email sender
# -----------------------
def send_email(sender, password, recipient, subject, data):
    try:
        body = "<h2>Daily Regulatory News Summary</h2><br>"
        total_articles = sum(len(arts) for arts in data.values())

        if total_articles == 0:
            body += "<p><i>No relevant articles found in the specified time window.</i></p>"
        else:
            for pair, articles in data.items():
                if not articles:
                    continue
                pair_name = pair.replace("_", " & ")
                body += f"<h3>{pair_name}</h3><ul style='line-height: 1.6;'>"
                for art in articles:
                    snippet = (art.get('content') or '')[:320].replace('\n', ' ')
                    if len(art.get('content') or '') > 320:
                        snippet += "..."
                    body += f"""
                    <li>
                        <b><a href="{art.get('url')}">{art.get('headline')}</a></b><br>
                        <small>{art.get('site_name')} • {art.get('published_at', 'Recently')}</small><br>
                        <p style="color:#444; margin:8px 0;">{snippet}</p>
                    </li><br>
                    """
                body += "</ul><hr>"

        msg = MIMEMultipart("alternative")
        msg["From"] = sender
        msg["To"] = recipient
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "html"))

        # Auto-detect SMTP
        if sender.endswith("@gmail.com"):
            smtp_server = "smtp.gmail.com"
        else:
            smtp_server = "smtp.office365.com"
        smtp_port = 587

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())

        print(f"Email sent: {sender} → {recipient} | {total_articles} articles")
    except Exception as e:
        print(f"[Email Error] {e}")


# -----------------------
# Main Runner
# -----------------------
def main():
    ist_now = datetime.now(pytz.timezone("Asia/Kolkata"))
    print(f"\nScript started at: {ist_now.strftime('%Y-%m-%d %H:%M:%S IST')}")

    # Founder: Today 7 AM – 10 AM IST
    print("\n===== Founder Job (Today 07:00 – 10:00 IST)")
    founder_data = fetch_news_for_keywords(
        keywords=BASE_KEYWORDS,
        time_filter_mode="today_7_to_10"
    )
    send_email(
        sender=os.getenv("FOUNDER_EMAIL"),
        password=os.getenv("FOUNDER_APP_PASSWORD"),
        recipient=os.getenv("FOUNDER_EMAIL"),
        subject=f"Regulatory Update – {ist_now.strftime('%b %d')} (7–10 AM)",
        data=founder_data,
    )

    # New Member: Yesterday 7 AM – 7 PM IST
    print("\n New Member Job (Yesterday 07:00 – 19:00 IST)")
    new_member_data = fetch_news_for_keywords(
        keywords=KEYWORDS_NEW_MEMBER,
        time_filter_mode="yesterday_7am_to_7pm"
    )
    yesterday_str = (ist_now - timedelta(days=1)).strftime("%b %d")
    send_email(
        sender=os.getenv("NEW_MEMBER_INPUT_EMAIL"),
        password=os.getenv("NEW_MEMBER_APP_PASSWORD"),
        recipient=os.getenv("NEW_MEMBER_OUTPUT_EMAIL"),
        subject=f"Regulatory & Fraud Alerts – {yesterday_str} (Full Day 7 AM – 7 PM)",
        data=new_member_data,
    )

    print("\nAll jobs completed.\n")


if __name__ == "__main__":
    main()