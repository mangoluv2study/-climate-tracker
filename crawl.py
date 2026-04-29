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


def summarize(text):
    msg = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{"role": "user", "content": "用繁體中文，三句話摘要以下氣候訴訟內容：\n\n" + text[:2000]}]
    )
    return msg.content[0].text


def crawl_news():
    for feed_url in NEWS_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:10]:
            try:
                summary = summarize(entry.get("summary", "") or entry.get("title", ""))
                row = {
                    "headline": entry.title,
                    "source": feed.feed.get("title", "Google News"),
                    "published_date": str(date.today()),
                    "url": entry.link,
                    "content_summary": summary,
                    "tags": ["climate", "litigation", "news"]
                }
                sb.table("news").upsert(row, on_conflict="url").execute()
                print("OK news: " + entry.title[:60])
            except Exception as e:
                print("ERR news: " + str(e))


def crawl_cases():
    for feed_url in CASES_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:10]:
            try:
                content = entry.get("summary", "") or ""
                if not content and entry.get("content"):
                    content = entry["content"][0].get("value", "")
                soup = BeautifulSoup(content, "html.parser")
                text = soup.get_text()[:2000]
                summary = summarize("案件標題：" + entry.title + "\n\n" + text)
                row = {
                    "title": entry.title,
                    "court": "",
                    "country": "",
                    "summary": summary,
                    "source_url": entry.link,
                    "tags": ["climate", "litigation", "case"]
                }
                sb.table("cases").upsert(row, on_conflict="source_url").execute()
                print("OK case: " + entry.title[:60])
            except Exception as e:
                print("ERR case: " + str(e))


if __name__ == "__main__":
    print("Starting crawl...")
    crawl_news()
    crawl_cases()
    print("Done.")
