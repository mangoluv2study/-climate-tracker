import os
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

def summarize(title, body):
    content = body if len(body) > 200 else ""
    if content:
        prompt = f"請用繁體中文寫三句話摘要以下氣候訴訟新聞，直接給出摘要，不要說「根據標題」或「若需全文」之類的話：\n\n標題：{title}\n\n內文：{content}"
    else:
        prompt = f"請用繁體中文寫三句話摘要以下氣候訴訟新聞標題，直接給出摘要，不要加任何說明或備註：\n\n{title}"
    msg = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text.strip()

def crawl_news():
    for feed_url in NEWS_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:10]:
            try:
                print(f"  fetching: {entry.title[:50]}")
                body = fetch_article_text(entry.link)
                summary = summarize(entry.title, body)
                row = {
                    "headline": entry.title,
                    "source": feed.feed.get("title", "Google News").replace(" - Google News",""),
                    "published_date": str(date.today()),
                    "url": entry.link,
                    "content_summary": summary,
                    "tags": ["climate", "litigation", "news"]
                }
                sb.table("news").upsert(row, on_conflict="url").execute()
                print(f"  OK: {entry.title[:60]}")
            except Exception as e:
                print(f"  ERR: {e}")

def crawl_cases():
    for feed_url in CASES_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:10]:
            try:
                print(f"  fetching case: {entry.title[:50]}")
                content = entry.get("summary", "") or ""
                if not content and entry.get("content"):
                    content = entry["content"][0].get("value", "")
                body = BeautifulSoup(content, "html.parser").get_text()
                if len(body) < 200:
                    body = fetch_article_text(entry.link)
                summary = summarize(entry.title, body)
                row = {
                    "title": entry.title,
                    "court": "",
                    "country": "",
                    "summary": summary,
                    "source_url": entry.link,
                    "tags": ["climate", "litigation", "case"]
                }
                sb.table("cases").upsert(row, on_conflict="source_url").execute()
                print(f"  OK case: {entry.title[:60]}")
            except Exception as e:
                print(f"  ERR case: {e}")

if __name__ == "__main__":
    print("Starting crawl...")
    crawl_news()
    crawl_cases()
    print("Done.")
