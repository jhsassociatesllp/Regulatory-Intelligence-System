import requests
import trafilatura
from datetime import datetime
import pytz
import time
import json
import os
from dotenv import load_dotenv
import smtplib
import json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import win32com.client as win32

load_dotenv()

# import win32com.client as win32

# # -----------------------
# Function: Send results via Outlook mail
# -----------------------
def send_email_via_outlook(json_file, recipient, subject="Daily Regulatory News Summary"):
    try:
        # Load JSON results
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Format email body in Markdown-style (but Outlook uses HTML, so we convert)
        body = "<h2>📢 Daily Regulatory News Summary</h2>"
        for pair, articles in data.items():
            body += f"<h3>🔎 Keywords: {pair.replace('_', ' & ')}</h3><ul>"
            for art in articles:
                headline = art.get("headline", "No title")
                url = art.get("url", "#")
                site = art.get("site_name", "Unknown Source")
                content = art.get("content", "")

                body += f"""
                <li>
                    <b>{headline}</b><br>
                    <i><a href="{url}">{site}</a></i><br>
                    <p>{content[:300]}...</p>
                </li>
                """
            body += "</ul><hr>"

        # Connect to Outlook
        outlook = win32.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)
        mail.To = recipient
        mail.Subject = subject
        mail.HTMLBody = body
        mail.Send()

        print(f"✅ Email sent to {recipient}")
    except Exception as e:
        print(f"[Email Error] {e}")



# -----------------------
# Configuration
# -----------------------
KEYWORDS = [
    "regulation", "compliance"
    # "regulation", "compliance", "SEBI", "RBI", "audit", "regulatory", "FEMA", "tax", "GST",
    # "statutory", "law", "legal", "enforcement", "guideline", "notification", "amendment",
    # "disclosure", "reporting", "KYC", "AML", "insider trading", "corporate governance",
    # "penalty", "IRDA", "NFRA", "ICAI", "FDI", "income tax"
]

SERP_API_KEYS = [
    os.getenv("SERPAPI_KEY1"),
    os.getenv("SERPAPI_KEY2"),
    os.getenv("SERPAPI_KEY3"),
    os.getenv("SERPAPI_KEY4")
]

DIFFBOT_KEYS = [
    os.getenv("DIFFBOT_TOKEN1"),
    os.getenv("DIFFBOT_TOKEN2"),
    os.getenv("DIFFBOT_TOKEN3")
]

# -----------------------
# Helper: Fetch content using trafilatura
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

# -----------------------
# Helper: Fetch content using Diffbot with retries
# -----------------------
def fetch_diffbot_content(url, token, max_retries=3, sleep_seconds=5):
    for attempt in range(max_retries):
        try:
            api_url = f"https://api.diffbot.com/v3/article?url={url}&token={token}"
            headers = {"accept": "application/json"}
            response = requests.get(api_url, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()
            if "objects" not in data or not data["objects"]:
                print(f"[Diffbot Error] No 'objects' in response for URL: {url}")
                return None
            article = data['objects'][0]
            return {
                "headline": article.get("title"),
                "author": article.get("author"),
                "site_name": article.get("siteName"),
                "content": article.get("text"),
                "url": article.get("pageUrl")
            }
        except Exception as e:
            print(f"[Diffbot Error] Attempt {attempt + 1}/{max_retries}: {e} for URL: {url}")
            if attempt < max_retries - 1:
                time.sleep(sleep_seconds)  # Wait before retrying
            continue
    return None

# -----------------------
# Function: Fetch SerpAPI News + Filter by Time
# -----------------------
def fetch_serpapi_news(query, serp_keys, diffbot_keys, max_retries=3, sleep_seconds=5):
    ist = pytz.timezone("Asia/Kolkata")
    results = []

    serp_index = 0
    diffbot_index = 0

    url = "https://serpapi.com/search"
    params_base = {
        "engine": "google_news",
        "q": f"site:economictimes.indiatimes.com OR site:business-standard.com OR site:financialexpress.com {query}",
        "tbs": "qdr:d"  # last 24 hours
    }

    for attempt in range(max_retries):
        serp_key = serp_keys[serp_index % len(serp_keys)]
        params = {**params_base, "api_key": serp_key}
        try:
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
            for item in data.get("news_results", []):
                link = item.get("link")
                date_str = item.get("date")
                try:
                    pub_dt = datetime.strptime(date_str, "%m/%d/%Y, %I:%M %p, +0000 UTC")
                    pub_dt = pub_dt.replace(tzinfo=pytz.UTC).astimezone(ist)
                except Exception as e:
                    print(f"[Date Parse Error] {e} for date: {date_str}")
                    continue

                if 7 <= pub_dt.hour < 10:
                    content = fetch_article_content(link)

                    if not content:
                        diffbot_token = diffbot_keys[diffbot_index % len(diffbot_keys)]
                        diffbot_index += 1
                        diff_data = fetch_diffbot_content(link, diffbot_token)
                        if diff_data:
                            results.append(diff_data)
                            time.sleep(sleep_seconds)  # Sleep after Diffbot call
                            continue

                    results.append({
                        "headline": item.get("title"),
                        "author": item.get("source", {}).get("name"),
                        "site_name": item.get("source", {}).get("name"),
                        "content": content,
                        "url": link
                    })
            break  # Success, break retry loop
        except Exception as e:
            print(f"[SerpAPI Error] Attempt {attempt + 1}/{max_retries}: {e}")
            serp_index += 1
            time.sleep(sleep_seconds)  # Wait before retry
            continue

    return results

# -----------------------
# Main function: Loop through consecutive keyword pairs
# -----------------------
def main():
    all_results = {}

    # Create consecutive pairs (e.g., [0,1], [2,3], [4,5], ...)
    for i in range(0, len(KEYWORDS) - 1, 2):
        keyword1 = KEYWORDS[i]
        keyword2 = KEYWORDS[i + 1]
        query = f"{keyword1} OR {keyword2}"
        print(f"\nFetching news for keywords: {keyword1}, {keyword2}")

        articles = fetch_serpapi_news(query, SERP_API_KEYS, DIFFBOT_KEYS)
        print(f"Found {len(articles)} articles for this pair.")

        all_results[f"{keyword1}_{keyword2}"] = articles
        time.sleep(10)  # Respect SerpAPI rate limits

    # Save to JSON
    # with open("filtered_news.json", "w", encoding="utf-8") as f:
    #     json.dump(all_results, f, indent=2, ensure_ascii=False)

    print("\n✅ Done! All results fetched from SerpAPI.")
    return all_results
    


# -----------------------
# Function: Send results via SMTP (App Password)
# -----------------------
def send_email_via_smtp(data, sender, app_password, recipient, subject="Daily Regulatory News Summary"):
    try:
        # Load JSON results
        # with open(json_file, "r", encoding="utf-8") as f:
        #     data = json.load(f)

        # Build email body (HTML)
        body = "<h2>📢 Daily Regulatory News Summary</h2>"

        for pair, articles in data.items():
            if not articles:   # Skip empty keywords
                continue

            # Show keyword heading
            body += f"<h3>🔎 {pair.replace('_', ' & ')}</h3><ul>"

            for art in articles:
                headline = art.get("headline", "No title")
                url = art.get("url", "#")
                site = art.get("site_name", "Unknown Source")
                content = art.get("content", "")

                body += f"""
                <li>
                    <b>{headline}</b><br>
                    <i><a href="{url}">{site}</a></i><br>
                    <p>{content[:300]}...</p>
                </li>
                """
            body += "</ul><hr>"

        # Create message
        msg = MIMEMultipart("alternative")
        msg["From"] = sender
        msg["To"] = recipient
        msg["Subject"] = subject

        # Attach body as HTML
        msg.attach(MIMEText(body, "html"))

        # --- SMTP setup (Outlook/Office365) ---
        smtp_server = "smtp.office365.com"
        smtp_port = 587

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()  # Secure connection
            server.login(sender, app_password)
            server.sendmail(sender, recipient, msg.as_string())

        print(f"✅ Email sent to {recipient}")

    except Exception as e:
        print(f"[Email Error] {e}")
        

if __name__ == "__main__":
    print("🚀 Script started:", datetime.now())
    main()
    print("✅ Fetching done, sending email...")

    try:
        send_email_via_smtp(
            json_file="filtered_news.json",
            sender=os.getenv("SENDER_EMAIL"),
            app_password=os.getenv("APP_PASSWORD"),
            recipient=os.getenv("SENDER_EMAIL"),
            subject="Daily Regulatory News - Summary"
        )
    except Exception as e:
        print("❌ Email sending failed:", e)
        raise  # <-- ensures GitHub Action marks it failed

    print("🎉 Script completed successfully!")
