import requests
import trafilatura
from datetime import datetime
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
    # "regulation", "compliance", "SEBI", "RBI", "audit", "regulatory", "FEMA", "tax", "GST",
    # "statutory", "law", "legal", "enforcement", "guideline", "notification", "amendment",
    # "disclosure", "reporting", "KYC", "AML", "insider trading", "corporate governance",
    # "penalty", "IRDA", "NFRA", "ICAI", "FDI", "income tax"
]

NEW_MEMBER_EXTRA_KEYWORDS = [
    "fraud", "case"
    # "fraud", "case", "scam", "concession", "waiver", "relief", "exemption", 
    # "violation", "breach", "investigation", "probe", "lawsuit", "litigation"
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
# Fetch SerpAPI News
# -----------------------
def fetch_serpapi_news(
    query,
    serp_keys,
    diffbot_keys,
    filter_start_hour=None,
    filter_end_hour=None,
    max_retries=3,
    sleep_seconds=5,
):
    ist = pytz.timezone("Asia/Kolkata")
    results = []

    serp_index = 0
    diffbot_index = 0

    url = "https://serpapi.com/search"
    params_base = {
        "engine": "google_news",
        "q": (
            "site:economictimes.indiatimes.com "
            "OR site:business-standard.com "
            "OR site:financialexpress.com "
            f"{query}"
        ),
        "tbs": "qdr:d"
    }

    for attempt in range(max_retries):
        serp_key = serp_keys[serp_index % len(serp_keys)]
        params = {**params_base, "api_key": serp_key}

        try:
            response = requests.get(url, params=params, timeout=15)
            data = response.json()

            for item in data.get("news_results", []):
                link = item.get("link")
                date_str = item.get("date")

                # Parse date
                try:
                    pub_dt = datetime.strptime(date_str, "%m/%d/%Y, %I:%M %p, +0000 UTC")
                    pub_dt = pub_dt.replace(tzinfo=pytz.UTC).astimezone(ist)
                except:
                    continue

                # Apply time window if needed
                if filter_start_hour is not None:
                    if not (filter_start_hour <= pub_dt.hour < filter_end_hour):
                        continue

                content = fetch_article_content(link)

                if not content:
                    diff_token = diffbot_keys[diffbot_index % len(diffbot_keys)]
                    diffbot_index += 1
                    diff_data = fetch_diffbot_content(link, diff_token)
                    if diff_data:
                        results.append(diff_data)
                        time.sleep(sleep_seconds)
                        continue

                results.append({
                    "headline": item.get("title"),
                    "author": item.get("source", {}).get("name"),
                    "site_name": item.get("source", {}).get("name"),
                    "content": content,
                    "url": link,
                })

            break

        except Exception as e:
            print(f"[SerpAPI Error {attempt+1}] {e}")
            serp_index += 1
            time.sleep(sleep_seconds)

    return results


# -----------------------
# Fetch for keyword pairs
# -----------------------
def fetch_news_for_keywords(keywords, filter_start_hour=None, filter_end_hour=None):
    all_results = {}

    for i in range(0, len(keywords) - 1, 2):
        k1 = keywords[i]
        k2 = keywords[i + 1]
        query = f"{k1} OR {k2}"

        print(f"\nFetching news for: {k1}, {k2}")

        articles = fetch_serpapi_news(
            query,
            SERP_API_KEYS,
            DIFFBOT_KEYS,
            filter_start_hour,
            filter_end_hour,
        )

        all_results[f"{k1}_{k2}"] = articles
        time.sleep(10)

    return all_results


# -----------------------
# Email sender
# -----------------------
# def send_email(sender, password, recipient, subject, data):
#     try:
#         body = "<h2>📢 Daily Regulatory News Summary</h2>"

#         for pair, articles in data.items():
#             if not articles:
#                 continue

#             body += f"<h3>{pair.replace('_', ' & ')}</h3><ul>"

#             for art in articles:
#                 body += f"""
#                 <li>
#                     <b>{art.get('headline')}</b><br>
#                     <a href="{art.get('url')}">{art.get('site_name')}</a><br>
#                     <p>{(art.get('content') or '')[:300]}...</p>
#                 </li>
#                 """

#             body += "</ul><hr>"

#         msg = MIMEMultipart("alternative")
#         msg["From"] = sender
#         msg["To"] = recipient
#         msg["Subject"] = subject
#         msg.attach(MIMEText(body, "html"))

#         with smtplib.SMTP("smtp.office365.com", 587) as server:
#             server.starttls()
#             server.login(sender, password)
#             server.sendmail(sender, recipient, msg.as_string())

#         print(f"✅ Email sent from {sender} → {recipient}")

#     except Exception as e:
#         print(f"[Email Error] {e}")

def send_email(sender, password, recipient, subject, data):
    try:
        body = "<h2>📢 Daily Regulatory News Summary</h2>"

        for pair, articles in data.items():
            if not articles:
                continue

            body += f"<h3>{pair.replace('_', ' & ')}</h3><ul>"

            for art in articles:
                body += f"""
                <li>
                    <b>{art.get('headline')}</b><br>
                    <a href="{art.get('url')}">{art.get('site_name')}</a><br>
                    <p>{(art.get('content') or '')[:300]}...</p>
                </li>
                """
            body += "</ul><hr>"

        msg = MIMEMultipart("alternative")
        msg["From"] = sender
        msg["To"] = recipient
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "html"))

        # ------------------------
        # SELECT SMTP BASED ON EMAIL
        # ------------------------
        if sender.endswith("@gmail.com"):
            smtp_server = "smtp.gmail.com"
            smtp_port = 587
        else:
            smtp_server = "smtp.office365.com"
            smtp_port = 587

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())

        print(f"✅ Email sent from {sender} → {recipient}")

    except Exception as e:
        print(f"[Email Error] {e}")


# -----------------------
# Main Runner
# -----------------------
def main():
    # Founder email credentials
    FOUNDER_EMAIL = os.getenv("FOUNDER_EMAIL")
    FOUNDER_APP_PASSWORD = os.getenv("FOUNDER_APP_PASSWORD")

    # New member email credentials
    NEW_MEMBER_INPUT_EMAIL = os.getenv("NEW_MEMBER_INPUT_EMAIL")
    NEW_MEMBER_OUTPUT_EMAIL = os.getenv("NEW_MEMBER_OUTPUT_EMAIL")
    NEW_MEMBER_APP_PASSWORD = os.getenv("NEW_MEMBER_APP_PASSWORD")

    # ---------------- Founder job ----------------
    print("\n===== Founder Job (07:00–10:00) =====")
    founder_data = fetch_news_for_keywords(
        BASE_KEYWORDS,
        filter_start_hour=7,
        filter_end_hour=10
    )

    send_email(
        sender=FOUNDER_EMAIL,
        password=FOUNDER_APP_PASSWORD,
        recipient=FOUNDER_EMAIL,
        subject="Daily Regulatory News - Founder",
        data=founder_data,
    )

    # ---------------- New member job ----------------
    print("\n===== New Member Job (Last 24 Hours) =====")
    new_member_data = fetch_news_for_keywords(
        KEYWORDS_NEW_MEMBER,
        filter_start_hour=None,
        filter_end_hour=None
    )

    send_email(
        sender=NEW_MEMBER_INPUT_EMAIL,
        password=NEW_MEMBER_APP_PASSWORD,
        recipient=NEW_MEMBER_OUTPUT_EMAIL,
        subject="Daily Regulatory News - Expanded (24 Hours)",
        data=new_member_data,
    )


if __name__ == "__main__":
    main()
