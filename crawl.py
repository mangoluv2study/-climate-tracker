import os, feedparser, requests, anthropic
from bs4 import BeautifulSoup
from supabase import create_client
from datetime import date

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

RSS_FEEDS = [
    "https://climatecasechart.com/feed/",
    "https://news.google.com/rss/search?q=climate+litigation+lawsuit&hl=en",
    "https://www.unep.org/news-and-stories/rss.xml",
]

def summarize(text):
    msg = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{"role":"user","content":
            f"用繁體中文，三句話摘要以下氣候訴訟新聞：\n\n{text[:2000]}"}]
    )
    return msg.content[0].text

def crawl_rss():
    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
        for entry in feed.entries[:10]:
            try:
                summary = summarize(entry.get("summary","") or entry.get("title",""))
                row = {
                    "headline": entry.title,
                    "source": feed.feed.get("title",""),
                    "published_date": str(date.today()),
                    "url": entry.link,
                    "content_summary": summary,
                    "tags": ["climate","litigation"]
                }
                sb.table("news").upsert(row, on_conflict="url").execute()
                print(f"✓ {entry.title[:60]}")
            except Exception as e:
                print(f"✗ {e}")

if __name__ == "__main__":
    print("Starting crawl...")
    crawl_rss()
    print("Done.")
