import requests
import trafilatura
from datetime import datetime, timedelta
import pytz
import time
import json
import os
import random
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
# Helper: Enhanced Content Fetching
# -----------------------
def fetch_article_content(url):
    try:
        # Add random delay to avoid rate limiting
        time.sleep(random.uniform(1, 3))
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            content = trafilatura.extract(downloaded)
            if content and len(content.strip()) > 50:  # Valid content
                return content.strip()
        return None
    except Exception as e:
        print(f"[Content Fetch Error] {e} for URL: {url}")
        return None


def fetch_diffbot_content(url, token, max_retries=3, sleep_seconds=5):
    for attempt in range(max_retries):
        try:
            time.sleep(random.uniform(2, 4))  # Random delay
            api_url = f"https://api.diffbot.com/v3/article?url={url}&token={token}"
            response = requests.get(api_url, timeout=20)
            data = response.json()
            
            if "objects" not in data or not data["objects"]:
                print(f"[Diffbot] No objects for {url}")
                return None
                
            article = data["objects"][0]
            content = article.get("text", "")
            if not content or len(content.strip()) < 100:
                return None
                
            return {
                "headline": article.get("title"),
                "author": article.get("author"),
                "site_name": article.get("siteName"),
                "content": content.strip(),
                "url": article.get("pageUrl"),
            }
        except Exception as e:
            print(f"[Diffbot Error] Attempt {attempt + 1}: {e}")
            time.sleep(sleep_seconds)
    return None


# -----------------------
# Enhanced SerpAPI News Fetching
# -----------------------
def fetch_serpapi_news(
    query,
    serp_keys,
    diffbot_keys,
    time_filter_mode="today_7_to_10",
    max_retries=5,  # Increased retries
    sleep_seconds=8,  # Increased delay
    force_fresh=False,  # Force fresh results
):
    ist = pytz.timezone("Asia/Kolkata")
    results = []
    serp_index = 0
    diffbot_index = 0
    total_attempts = 0

    url = "https://serpapi.com/search"
    
    # Enhanced base query with more sites and better parameters
    params_base = {
        "engine": "google_news",
        "q": (
            "site:economictimes.indiatimes.com "
            "OR site:business-standard.com "
            "OR site:financialexpress.com "
            "OR site:moneycontrol.com "
            "OR site:livemint.com "
            f"{query}"
        ),
        "hl": "en",
        "gl": "in",
        "lr": "lang_en",  # English language
        "num": "20",  # Get more results
    }

    # Set date range based on mode
    if time_filter_mode == "today_7_to_10":
        params_base["tbs"] = "qdr:d"  # today only
    elif time_filter_mode == "yesterday_7am_to_7pm":
        # Use specific date range for yesterday
        now_ist = datetime.now(ist)
        yesterday = now_ist - timedelta(days=1)
        yesterday_str = yesterday.strftime("%Y-%m-%d")
        params_base["tbs"] = f"cdr:1,cd_min:{yesterday_str},cd_max:{yesterday_str}"
        print(f"[DEBUG] Yesterday date range: {yesterday_str}")
    else:
        params_base["tbs"] = "qdr:d"

    # Add cache-busting parameter
    if force_fresh:
        params_base["tbs"] += f",sbd:1"  # Sort by date (fresh)

    print(f"[DEBUG] Query: {query} | Mode: {time_filter_mode} | TBS: {params_base.get('tbs', 'N/A')}")

    for attempt in range(max_retries):
        total_attempts += 1
        serp_key = serp_keys[serp_index % len(serp_keys)]
        params = {**params_base, "api_key": serp_key}

        try:
            # Random delay between requests
            if attempt > 0:
                delay = random.uniform(sleep_seconds, sleep_seconds + 3)
                print(f"[WAIT] Sleeping {delay:.1f}s before attempt {attempt + 1}")
                time.sleep(delay)

            print(f"[SerpAPI] Attempt {attempt + 1}/{max_retries} with key {serp_index + 1}")
            response = requests.get(url, params=params, timeout=25)
            response.raise_for_status()
            data = response.json()

            if "search_metadata" not in data:
                print(f"[SerpAPI] Invalid response structure")
                raise Exception("Invalid API response")

            news_results = data.get("news_results", [])
            print(f"[SerpAPI] Found {len(news_results)} news results")

            if not news_results:
                print(f"[SerpAPI] No news results for query: {query}")
                serp_index += 1
                continue

            valid_articles = 0
            for idx, item in enumerate(news_results):
                link = item.get("link")
                title = item.get("title")
                source_name = item.get("source", {}).get("name", "Unknown")
                date_str = item.get("date")

                if not link or not title or not date_str:
                    print(f"[SKIP] Invalid item {idx}: missing link/title/date")
                    continue

                # Parse published date with better error handling
                try:
                    # Handle different date formats
                    date_part = date_str.split(", +0000 UTC")[0] if ", +0000 UTC" in date_str else date_str
                    pub_dt = datetime.strptime(date_part, "%m/%d/%Y, %I:%M %p")
                    pub_dt = pub_dt.replace(tzinfo=pytz.UTC).astimezone(ist)
                except ValueError:
                    try:
                        # Alternative format: "Dec 8, 2025, 3:30 PM"
                        pub_dt = datetime.strptime(date_str, "%b %d, %Y, %I:%M %p")
                        pub_dt = pub_dt.replace(tzinfo=pytz.UTC).astimezone(ist)
                    except ValueError as e2:
                        print(f"[Date Parse Error] {date_str} -> {e2}")
                        continue

                now_ist = datetime.now(ist)

                # === Enhanced Time Filtering ===
                keep_article = False
                if time_filter_mode == "today_7_to_10":
                    if pub_dt.date() == now_ist.date() and 7 <= pub_dt.hour < 10:
                        keep_article = True
                elif time_filter_mode == "yesterday_7am_to_7pm":
                    yesterday = now_ist - timedelta(days=1)
                    if (pub_dt.date() == yesterday.date() and 
                        7 <= pub_dt.hour < 19):
                        keep_article = True

                if not keep_article:
                    print(f"[FILTER] Skipping {title[:60]}... (outside time window)")
                    continue

                print(f"[PROCESS] {title[:60]}... | {pub_dt.strftime('%H:%M IST')} | {source_name}")

                # === Fetch Content ===
                content = fetch_article_content(link)
                if content and len(content) > 100:
                    article_data = {
                        "headline": title,
                        "author": None,
                        "site_name": source_name,
                        "content": content,
                        "url": link,
                        "published_at": pub_dt.strftime("%Y-%m-%d %H:%M IST")
                    }
                    results.append(article_data)
                    valid_articles += 1
                    print(f"[SUCCESS] Added article {valid_articles}")
                else:
                    # Try Diffbot as fallback
                    diff_token = diffbot_keys[diffbot_index % len(diffbot_keys)]
                    diffbot_index += 1
                    diff_data = fetch_diffbot_content(link, diff_token)
                    if diff_data:
                        diff_data["published_at"] = pub_dt.strftime("%Y-%m-%d %H:%M IST")
                        results.append(diff_data)
                        valid_articles += 1
                        print(f"[DIFFBOT] Added article {valid_articles}")
                    else:
                        print(f"[CONTENT FAIL] Both trafilatura & Diffbot failed for {link}")

                # Rate limiting between articles
                if valid_articles < len(news_results):  # Not the last one
                    time.sleep(random.uniform(3, 6))

            print(f"[SUMMARY] Processed {len(news_results)} results, kept {valid_articles} valid articles")
            
            if valid_articles > 0:
                print(f"[SUCCESS] Returning {len(results)} articles for {query}")
                break  # Success - exit retry loop
            else:
                print(f"[WARNING] No valid articles found, retrying...")

        except requests.exceptions.RequestException as e:
            print(f"[Network Error {attempt+1}] {e}")
            serp_index += 1
        except Exception as e:
            print(f"[SerpAPI Error {attempt+1}] {e}")
            serp_index += 1

        if attempt < max_retries - 1:
            wait_time = random.uniform(10, 15)
            print(f"[RETRY] Waiting {wait_time:.1f}s before next attempt...")
            time.sleep(wait_time)

    print(f"[FINAL] Total attempts: {total_attempts} | Results: {len(results)}")
    return results


# -----------------------
# Fetch for keyword pairs
# -----------------------
def fetch_news_for_keywords(keywords, time_filter_mode, force_fresh=False):
    all_results = {}
    print(f"\n🔍 Starting keyword search | Mode: {time_filter_mode} | Fresh: {force_fresh}")
    
    for i in range(0, len(keywords) - 1, 2):
        k1 = keywords[i]
        k2 = keywords[i + 1]
        query = f'("{k1}" OR "{k2}")'  # Quote keywords for better matching
        print(f"\n📝 Processing: {k1} OR {k2}")
        
        articles = fetch_serpapi_news(
            query=query,
            serp_keys=SERP_API_KEYS,
            diffbot_keys=DIFFBOT_KEYS,
            time_filter_mode=time_filter_mode,
            force_fresh=force_fresh,
        )
        
        key = f"{k1}_{k2}"
        all_results[key] = articles
        print(f"✅ {key}: {len(articles)} articles found")
        
        # Longer delay between keyword pairs
        if i < len(keywords) - 2:
            delay = random.uniform(15, 25)
            print(f"⏳ Waiting {delay:.1f}s before next keyword pair...")
            time.sleep(delay)

    total_articles = sum(len(arts) for arts in all_results.values())
    print(f"\n📊 SUMMARY: {total_articles} total articles across {len(all_results)} keyword pairs")
    return all_results


# -----------------------
# Enhanced Email Sender
# -----------------------
def send_email(sender, password, recipient, subject, data, time_window=""):
    try:
        total_articles = sum(len(arts) for arts in data.values())
        
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 800px; margin: 0 auto; padding: 20px;">
                <h1 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px;">
                    📢 Regulatory News Summary
                </h1>
                
                <div style="background: #f8f9fa; padding: 15px; border-left: 4px solid #3498db; margin-bottom: 20px;">
                    <p><strong>Time Window:</strong> {time_window}</p>
                    <p><strong>Total Articles:</strong> {total_articles}</p>
                    <p><small>Generated: {datetime.now(pytz.timezone("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S IST")}</small></p>
                </div>
        """

        if total_articles == 0:
            body += """
                <div style="text-align: center; padding: 40px; color: #7f8c8d;">
                    <h3>📭 No New Articles Found</h3>
                    <p>No relevant regulatory news found in the specified time window.</p>
                </div>
            """
        else:
            for pair, articles in data.items():
                if not articles:
                    continue
                    
                pair_name = pair.replace("_", " & ").title()
                body += f"""
                    <h2 style="color: #2c3e50; margin-top: 30px;">
                        {pair_name}
                    </h2>
                    <div style="background: white; border: 1px solid #e9ecef; border-radius: 8px; padding: 20px; margin-bottom: 20px;">
                """
                
                for art in articles:
                    snippet = (art.get('content') or '')[:350].replace('\n', ' ').strip()
                    if len(art.get('content') or '') > 350:
                        snippet += "... <a href='#'>[Read more]</a>"
                    
                    body += f"""
                        <div style="border-bottom: 1px solid #e9ecef; padding: 15px 0;">
                            <h3 style="margin: 0 0 8px 0; color: #2c3e50;">
                                <a href="{art.get('url')}" style="text-decoration: none; color: #3498db;">
                                    {art.get('headline')}
                                </a>
                            </h3>
                            <p style="margin: 5px 0; color: #7f8c8d; font-size: 14px;">
                                <strong>{art.get('site_name')}</strong> • 
                                {art.get('published_at', 'Recently')}
                            </p>
                            <p style="margin: 10px 0; color: #555; line-height: 1.5;">
                                {snippet}
                            </p>
                        </div>
                    """
                
                body += "</div>"

        body += """
                <hr style="margin: 40px 0;">
                <div style="text-align: center; color: #7f8c8d; font-size: 14px;">
                    <p>This is an automated regulatory intelligence report.</p>
                    <p>Questions? Reply to this email.</p>
                </div>
            </div>
        </body>
        </html>
        """

        msg = MIMEMultipart("alternative")
        msg["From"] = sender
        msg["To"] = recipient
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "html"))

        # Auto-detect SMTP
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

        print(f"✅ Email sent: {sender} → {recipient} | {total_articles} articles | {time_window}")
        
    except Exception as e:
        print(f"[Email Error] {e}")
        import traceback
        traceback.print_exc()


# -----------------------
# Main Runner
# -----------------------
def main():
    ist_now = datetime.now(pytz.timezone("Asia/Kolkata"))
    print(f"\n🚀 Regulatory News Pipeline Started: {ist_now.strftime('%Y-%m-%d %H:%M:%S IST')}")
    print(f"Environment: {'Local' if os.getenv('DEVELOPMENT') else 'Production'}")

    # Random startup delay to avoid simultaneous runs
    startup_delay = random.uniform(5, 15)
    print(f"⏳ Startup delay: {startup_delay:.1f}s")
    time.sleep(startup_delay)

    # Founder: Today 7 AM – 10 AM IST
    print("\n" + "="*60)
    print("👑 FOUNDER BRIEFING: Today 07:00 – 10:00 IST")
    print("="*60)
    
    founder_data = fetch_news_for_keywords(
        keywords=BASE_KEYWORDS,
        time_filter_mode="today_7_to_10",
        force_fresh=True  # Always fresh for founder
    )
    
    founder_time_window = f"Today • {ist_now.strftime('%b %d')} • 07:00–10:00 IST"
    send_email(
        sender=os.getenv("FOUNDER_EMAIL"),
        password=os.getenv("FOUNDER_APP_PASSWORD"),
        recipient=os.getenv("FOUNDER_EMAIL"),
        subject=f"🚨 Regulatory Morning Brief | {ist_now.strftime('%b %d')}",
        data=founder_data,
        time_window=founder_time_window
    )

    # New Member: Yesterday 7 AM – 7 PM IST
    print("\n" + "="*60)
    print("👤 NEW MEMBER BRIEFING: Yesterday 07:00 – 19:00 IST")
    print("="*60)
    
    yesterday = ist_now - timedelta(days=1)
    new_member_data = fetch_news_for_keywords(
        keywords=KEYWORDS_NEW_MEMBER,
        time_filter_mode="yesterday_7am_to_7pm",
        force_fresh=True  # Force fresh results
    )
    
    new_member_time_window = f"Yesterday • {yesterday.strftime('%b %d')} • 07:00–19:00 IST"
    send_email(
        sender=os.getenv("NEW_MEMBER_INPUT_EMAIL"),
        password=os.getenv("NEW_MEMBER_APP_PASSWORD"),
        recipient=os.getenv("NEW_MEMBER_OUTPUT_EMAIL"),
        subject=f"📋 Regulatory & Risk Alert | {yesterday.strftime('%b %d')} Full Day",
        data=new_member_data,
        time_window=new_member_time_window
    )

    print("\n" + "="*60)
    print("✅ ALL JOBS COMPLETED SUCCESSFULLY")
    print("="*60)
    print(f"Final timestamp: {datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%H:%M:%S IST')}\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️  Script interrupted by user")
    except Exception as e:
        print(f"\n💥 CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()