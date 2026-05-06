import os
import json
import time
import feedparser
import requests
import anthropic
from bs4 import BeautifulSoup
from supabase import create_client
from datetime import date

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

JUDICIAL_ACCOUNT = os.environ.get("JUDICIAL_ACCOUNT", "")
JUDICIAL_PASSWORD = os.environ.get("JUDICIAL_PASSWORD", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
}

# Google News RSS - 英文
NEWS_FEEDS_EN = [
    "https://news.google.com/rss/search?q=climate+litigation+lawsuit&hl=en",
    "https://news.google.com/rss/search?q=climate+change+court+ruling&hl=en",
]

# Google News RSS - 中文（抓中國/亞洲相關）
NEWS_FEEDS_ZH = [
    "https://news.google.com/rss/search?q=%E6%B0%A3%E5%80%99%E8%A8%B4%E8%A8%9F&hl=zh-TW&gl=TW",
    "https://news.google.com/rss/search?q=%E7%A2%B3%E6%8E%92%E6%94%BE+%E6%B3%95%E9%99%A2&hl=zh-TW&gl=TW",
    "https://news.google.com/rss/search?q=%E6%B0%94%E5%80%99%E8%AF%89%E8%AE%BC+%E4%B8%AD%E5%9B%BD&hl=zh-CN&gl=CN",
    "https://news.google.com/rss/search?q=%E7%A2%B3%E6%8E%92%E6%94%BE+%E8%B5%94%E5%81%BF+%E6%B3%95%E9%99%A2&hl=zh-CN&gl=CN",
]

# Sabin Center cases
CASES_FEEDS = [
    "https://climate.law.columbia.edu/rss.xml",
]

# 替代 ECOLEX - 可以從 GitHub Actions 存取的來源
ALT_CASE_FEEDS = [
    "https://www.climatechangenews.com/feed/",
    "https://climatecasechart.com/feed/",
]

TAIWAN_KEYWORDS = ["氣候變遷", "碳排放", "溫室氣體"]

new_news = []
new_cases = []

# ── HELPERS ──────────────────────────────────────────

def fetch_text(url):
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
    prompt = f"""請分析以下氣候訴訟內容，回傳 JSON 格式，不要加任何說明或 markdown：

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
    raw = msg.content[0].text.strip().replace("```json","").replace("```","").strip()
    return json.loads(raw)

def upsert_case(row):
    existing = sb.table("cases").select("id").eq("source_url", row["source_url"]).execute()
    is_new = len(existing.data) == 0
    sb.table("cases").upsert(row, on_conflict="source_url").execute()
    if is_new:
        new_cases.append(row)
    return is_new

def upsert_news(row):
    existing = sb.table("news").select("id").eq("url", row["url"]).execute()
    is_new = len(existing.data) == 0
    sb.table("news").upsert(row, on_conflict="url").execute()
    if is_new:
        new_news.append(row)
    return is_new

# ── SOURCE 1: Google News 英文 ────────────────────────

def crawl_google_news_en():
    print("\n=== Google News（英文）===")
    for feed_url in NEWS_FEEDS_EN:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:10]:
            try:
                print(f"  {entry.title[:55]}")
                body = fetch_text(entry.link)
                result = analyze(entry.title, body)
                row = {
                    "headline": entry.title,
                    "source": "Google News",
                    "published_date": str(date.today()),
                    "url": entry.link,
                    "content_summary": result.get("summary",""),
                    "defendant_type": result.get("defendant_type","不明"),
                    "legal_cause": result.get("legal_cause","不明"),
                    "court_stage": result.get("court_stage","不明"),
                    "topic_tags": result.get("topic_tags",[]),
                    "tags": ["climate","litigation","news","en"]
                }
                status = "NEW" if upsert_news(row) else "UPD"
                print(f"  {status}: {row['defendant_type']} | {row['legal_cause']}")
            except Exception as e:
                print(f"  ERR: {e}")

# ── SOURCE 2: Google News 中文（亞洲）────────────────

def crawl_google_news_zh():
    print("\n=== Google News（中文/亞洲）===")
    for feed_url in NEWS_FEEDS_ZH:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:8]:
            try:
                print(f"  {entry.title[:55]}")
                body = fetch_text(entry.link)
                result = analyze(entry.title, body)
                row = {
                    "headline": entry.title,
                    "source": "Google News 亞洲",
                    "published_date": str(date.today()),
                    "url": entry.link,
                    "content_summary": result.get("summary",""),
                    "defendant_type": result.get("defendant_type","不明"),
                    "legal_cause": result.get("legal_cause","不明"),
                    "court_stage": result.get("court_stage","不明"),
                    "topic_tags": result.get("topic_tags",[]),
                    "tags": ["climate","litigation","news","asia"]
                }
                status = "NEW" if upsert_news(row) else "UPD"
                print(f"  {status}: {row['defendant_type']} | {row['legal_cause']}")
            except Exception as e:
                print(f"  ERR: {e}")

# ── SOURCE 3: Sabin Center ───────────────────────────

def crawl_sabin():
    print("\n=== Sabin Center ===")
    for feed_url in CASES_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:10]:
            try:
                print(f"  {entry.title[:55]}")
                content = entry.get("summary","") or ""
                if not content and entry.get("content"):
                    content = entry["content"][0].get("value","")
                body = BeautifulSoup(content, "html.parser").get_text()
                if len(body) < 200:
                    body = fetch_text(entry.link)
                result = analyze(entry.title, body)
                row = {
                    "title": entry.title,
                    "court": result.get("court_stage",""),
                    "country": "",
                    "summary": result.get("summary",""),
                    "source_url": entry.link,
                    "full_text_url": entry.link,
                    "defendant_type": result.get("defendant_type","不明"),
                    "legal_cause": result.get("legal_cause","不明"),
                    "court_stage": result.get("court_stage","不明"),
                    "topic_tags": result.get("topic_tags",[]),
                    "tags": ["climate","litigation","case","sabin"]
                }
                status = "NEW" if upsert_case(row) else "UPD"
                print(f"  {status}: {row['defendant_type']} | {row['legal_cause']}")
            except Exception as e:
                print(f"  ERR: {e}")

# ── SOURCE 4: Climate Home News + Climate Case Chart ─

def crawl_alt_cases():
    print("\n=== Climate Home News / Climate Case Chart ===")
    for feed_url in ALT_CASE_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            if not feed.entries:
                print(f"  無法讀取：{feed_url}")
                continue
            for entry in feed.entries[:8]:
                try:
                    print(f"  {entry.title[:55]}")
                    content = entry.get("summary","") or ""
                    body = BeautifulSoup(content, "html.parser").get_text()
                    if len(body) < 200:
                        body = fetch_text(entry.link)
                    result = analyze(entry.title, body)
                    row = {
                        "title": entry.title,
                        "court": result.get("court_stage",""),
                        "country": "",
                        "summary": result.get("summary",""),
                        "source_url": entry.link,
                        "full_text_url": entry.link,
                        "defendant_type": result.get("defendant_type","不明"),
                        "legal_cause": result.get("legal_cause","不明"),
                        "court_stage": result.get("court_stage","不明"),
                        "topic_tags": result.get("topic_tags",[]),
                        "tags": ["climate","litigation","case","international"]
                    }
                    status = "NEW" if upsert_case(row) else "UPD"
                    print(f"  {status}: {row['defendant_type']} | {row['legal_cause']}")
                    time.sleep(1)
                except Exception as e:
                    print(f"  item ERR: {e}")
        except Exception as e:
            print(f"  feed ERR: {e}")

# ── SOURCE 5: 台灣司法院 API ─────────────────────────

def get_judicial_token():
    try:
        resp = requests.post(
            "https://data.judicial.gov.tw/jdg/api/Auth",
            json={"account": JUDICIAL_ACCOUNT, "password": JUDICIAL_PASSWORD},
            timeout=10
        )
        data = resp.json()
        token = data.get("token","")
        if token:
            print(f"  Token 取得成功")
        else:
            print(f"  Token 失敗：{data}")
        return token
    except Exception as e:
        print(f"  登入失敗：{e}")
        return ""

def crawl_taiwan_court():
    print("\n=== 台灣司法院 ===")
    if not JUDICIAL_ACCOUNT or not JUDICIAL_PASSWORD:
        print("  未設定帳號密碼，跳過")
        return
    token = get_judicial_token()
    if not token:
        return
    headers = {**HEADERS, "Authorization": f"Bearer {token}"}
    for kw in TAIWAN_KEYWORDS:
        try:
            resp = requests.get(
                "https://data.judicial.gov.tw/jdg/api/JList",
                params={"kw": kw, "pg": 1},
                headers=headers,
                timeout=15
            )
            data = resp.json()
            items = data if isinstance(data, list) else data.get("data", [])
            for item in items[:5]:
                try:
                    jid = item.get("JID","")
                    title = item.get("JTITLE","") or item.get("JFULLCASE","") or jid
                    court = item.get("JCOURTNAME","")
                    full_url = f"https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id={jid}"
                    pdf_url = item.get("JFULLPDF","") or full_url
                    print(f"  {title[:55]}")
                    body = ""
                    try:
                        detail = requests.get(
                            "https://data.judicial.gov.tw/jdg/api/JDoc",
                            params={"jid": jid},
                            headers=headers,
                            timeout=15
                        ).json()
                        body = detail.get("JFULL","")[:3000]
                    except:
                        pass
                    result = analyze(title, body)
                    row = {
                        "title": title,
                        "court": court,
                        "country": "台灣",
                        "summary": result.get("summary",""),
                        "source_url": full_url,
                        "full_text_url": pdf_url,
                        "defendant_type": result.get("defendant_type","不明"),
                        "legal_cause": result.get("legal_cause","不明"),
                        "court_stage": result.get("court_stage","不明"),
                        "topic_tags": result.get("topic_tags",[kw]),
                        "tags": ["climate","litigation","case","taiwan"]
                    }
                    status = "NEW" if upsert_case(row) else "UPD"
                    print(f"  {status}: {court} | {row['legal_cause']}")
                    time.sleep(1)
                except Exception as e:
                    print(f"  item ERR: {e}")
            time.sleep(2)
        except Exception as e:
            print(f"  kw '{kw}' ERR: {e}")

# ── EMAIL BODY ────────────────────────────────────────

def write_email_body():
    today = str(date.today())
    lines = []
    lines.append(f"📅 {today} 氣候訴訟每日摘要")
    lines.append(f"新增新聞：{len(new_news)} 筆　新增案件：{len(new_cases)} 筆")
    lines.append("")
    if new_cases:
        lines.append("━━ 新增訴訟案件 ━━")
        for c in new_cases:
            tags = "、".join(c.get("topic_tags",[]))
            country = c.get("country","")
            lines.append(f"▸ {c['title']}")
            if country: lines.append(f"  國家：{country}")
            lines.append(f"  {c['defendant_type']} | {c['legal_cause']} | {c['court_stage']}")
            if tags: lines.append(f"  議題：{tags}")
            lines.append(f"  摘要：{c['summary'][:100]}...")
            lines.append(f"  連結：{c['source_url']}")
            lines.append("")
    if new_news:
        lines.append("━━ 新增新聞報導 ━━")
        for n in new_news:
            tags = "、".join(n.get("topic_tags",[]))
            lines.append(f"▸ {n['headline']}")
            lines.append(f"  {n['defendant_type']} | {n['legal_cause']} | {n['court_stage']}")
            if tags: lines.append(f"  議題：{tags}")
            lines.append(f"  摘要：{n['content_summary'][:100]}...")
            lines.append(f"  連結：{n['url']}")
            lines.append("")
    if not new_news and not new_cases:
        lines.append("今日無新增資料，所有來源均為最新狀態。")
        lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("前往 Dashboard 查看完整資料：")
    lines.append("https://climate-tracker-q3mo-nnxf95tyd-tys-projects-f3fb6178.vercel.app")
    body = "\n".join(lines)
    with open("email_body.txt", "w", encoding="utf-8") as f:
        f.write(body)
    print("\n=== EMAIL PREVIEW ===")
    print(body)

# ── MAIN ─────────────────────────────────────────────

if __name__ == "__main__":
    print("Starting crawl...")
    crawl_google_news_en()
    crawl_google_news_zh()
    crawl_sabin()
    crawl_alt_cases()
    crawl_taiwan_court()
    write_email_body()
    print("\nAll done.")
