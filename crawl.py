import os
import feedparser
import requests
import anthropic
from bs4 import BeautifulSoup
from supabase import create_client
from datetime import date

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

RSS_FEEDS = [
    "https://news.google.com/rss/search?q=climate+litigation+lawsuit&hl=en",
    "https://news.google.com/rss/search?q=climate+change+court+ruling&hl=en",
]


def summarize(text):
    msg = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{"role": "user", "content": "用繁體中文，三句話摘要以下氣候訴訟新聞：\n\n" + text[:2000]}]
    )
    return msg.content[0].text


def crawl_news():
    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:10]:
            try:
                summary = summarize(entry.get("summary", "") or entry.get("title", ""))
                row = {
                    "headline": entry.title,
                    "source": feed.feed.get("title", ""),
                    "published_date": str(date.today()),
                    "url": entry.link,
                    "content_summary": summary,
                    "tags": ["climate", "litigation"]
                }
                sb.table("news").upsert(row, on_conflict="url").execute()
                print("OK: " + entry.title[:60])
            except Exception as e:
                print("ERR: " + str(e))


def crawl_cases():
    try:
        api_url = "https://climatecasechart.com/wp-json/wp/v2/posts"
        resp = requests.get(api_url, params={"per_page": 20}, timeout=15)
        posts = resp.json()
        for post in posts:
            try:
                title = post.get("title", {}).get("rendered", "")
                html = post.get("content", {}).get("rendered", "")
                text = BeautifulSoup(html, "html.parser").get_text()[:2000]
                summary = summarize("案件名稱：" + title + "\n\n" + text)
                row = {
                    "title": title,
                    "court": "",
                    "country": "",
                    "summary": summary,
                    "source_url": post.get("link", ""),
                    "tags": ["climate", "litigation"]
                }
                sb.table("cases").upsert(row, on_conflict="source_url").execute()
                print("OK case: " + title[:60])
            except Exception as e:
                print("ERR case: " + str(e))
    except Exception as e:
        print("ERR cases: " + str(e))


if __name__ == "__main__":
    print("Starting crawl...")
    crawl_news()
    crawl_cases()
    print("Done.")
