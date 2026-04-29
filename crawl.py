import os
import json
import feedparser
import requests
import anthropic
from bs4 import BeautifulSoup
from supabase import create_client
from datetime import date

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

NEWS_FEEDS = [
    "https://news.google.com/rss/search?q=climate+litigation+lawsuit&hl=en",
    "https://news.google.com/rss/search?q=climate+change+court+ruling&hl=en",
]

CASES_FEEDS = [
    "https://climate.law.columbia.edu/rss.xml",
    "https://news.google.com/rss/search?q=climate+case+chart+ruling+court&hl=en",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
}

def fetch_article_text(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script","style","nav","header","footer","aside","figure","iframe"]):
            tag.decompose()
        paragraphs = soup.find_all("p")
        text = " ".join(p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 40)
        return text[:3000] if text else ""
    except Exception as e:
        print(f"  fetch failed: {e}")
        return ""

def analyze(title, body):
    content = body if len(body) > 200 else ""
    prompt = f"""請分析以下氣候訴訟新聞，回傳 JSON 格式，不要加任何說明或 markdown：

標題：{title}
內文：{content[:2000] if content else '（無內文）'}

請回傳以下 JSON（所有欄位用繁體中文）：
{{
  "summary": "三句話摘要，直接描述案件內容",
  "defendant_type": "只能是以下其中一個：政府被告、企業被告、金融機構、不明",
  "legal_cause": "只能是以下其中一個：侵權行為、違憲／人權、行政不作為、刑事訴追、資訊揭露、不明",
  "court_stage": "只能是以下其中一個：國際法院、最高法院、上訴審、一審、不明",
  "topic_tags": ["從以下選1-3個最相關的：石化燃料、排放責任、淨零路徑、漂綠、資訊揭露、巴黎協定、ESG永續、洪災海升、野火、原住民族、青年訴訟、氣候調適"]
}}"""

    msg = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = msg.content[0].text.strip()
    raw = raw.replace("```json","").replace("```","").strip()
    return json.loads(raw)

def crawl_news():
    for feed_url in NEWS_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:10]:
            try:
                print(f"  fetching: {entry.title[:50]}")
                body = fetch_article_text(entry.link)
                result = analyze(entry.title, body)
                row = {
                    "headline": entry.title,
                    "source": feed.feed.get("title", "Google News").replace(" - Google News",""),
                    "published_date": str(date.today()),
                    "url": entry.link,
                    "content_summary": result.get("summary",""),
                    "defendant_type": result.get("defendant_type","不明"),
                    "legal_cause": result.get("legal_cause","不明"),
                    "court_stage": result.get("court_stage","不明"),
                    "topic_tags": result.get("topic_tags",[]),
                    "tags": ["climate","litigation","news"]
                }
                sb.table("news").upsert(row, on_conflict="url").execute()
                print(f"  OK: {entry.title[:50]} | {row['defendant_type']} | {row['legal_cause']} | {row['court_stage']}")
            except Exception as e:
                print(f"  ERR: {e}")

def crawl_cases():
    for feed_url in CASES_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:10]:
            try:
                print(f"  fetching case: {entry.title[:50]}")
                content = entry.get("summary","") or ""
                if not content and entry.get("content"):
                    content = entry["content"][0].get("value","")
                body = BeautifulSoup(content, "html.parser").get_text()
                if len(body) < 200:
                    body = fetch_article_text(entry.link)
                result = analyze(entry.title, body)
                row = {
                    "title": entry.title,
                    "court": result.get("court_stage",""),
                    "country": "",
                    "summary": result.get("summary",""),
                    "source_url": entry.link,
                    "defendant_type": result.get("defendant_type","不明"),
                    "legal_cause": result.get("legal_cause","不明"),
                    "court_stage": result.get("court_stage","不明"),
                    "topic_tags": result.get("topic_tags",[]),
                    "tags": ["climate","litigation","case"]
                }
                sb.table("cases").upsert(row, on_conflict="source_url").execute()
                print(f"  OK case: {entry.title[:50]} | {row['defendant_type']} | {row['legal_cause']}")
            except Exception as e:
                print(f"  ERR case: {e}")

if __name__ == "__main__":
    print("Starting crawl...")
    crawl_news()
    crawl_cases()
    print("Done.")
