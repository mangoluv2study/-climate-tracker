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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
}

NEWS_FEEDS = [
    "https://news.google.com/rss/search?q=climate+litigation+lawsuit&hl=en",
    "https://news.google.com/rss/search?q=climate+change+court+ruling&hl=en",
]

CASES_FEEDS = [
    "https://climate.law.columbia.edu/rss.xml",
]

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

# ── SOURCE 1: Google News RSS ────────────────────────

def crawl_google_news():
    print("\n=== Google News ===")
    for feed_url in NEWS_FEEDS:
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
                    "tags": ["climate","litigation","news"]
                }
                status = "NEW" if upsert_news(row) else "UPD"
                print(f"  {status}: {row['defendant_type']} | {row['legal_cause']}")
            except Exception as e:
                print(f"  ERR: {e}")

# ── SOURCE 2: Sabin Center RSS ───────────────────────

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

# ── SOURCE 3: 台灣司法院裁判書 ──────────────────────

def crawl_taiwan_court():
    print("\n=== 台灣司法院 ===")
    keywords = ["氣候變遷", "碳排放", "溫室氣體"]
    base_url = "https://judgment.judicial.gov.tw/FJUD/qryresult.aspx"

    for kw in keywords:
        try:
            params = {
                "jud_year": "",
                "jud_case": "",
                "jud_no": "",
                "jud_type": "最高法院,高等法院",
                "searchWord": kw,
                "judtype": "判決",
                "pg": "1"
            }
            resp = requests.get(
                "https://judgment.judicial.gov.tw/FJUD/qryresult.aspx",
                params=params,
                headers=HEADERS,
                timeout=15
            )
            soup = BeautifulSoup(resp.text, "html.parser")
            rows = soup.select("table.table tr")[1:6]

            for tr in rows:
                try:
                    tds = tr.find_all("td")
                    if len(tds) < 3:
                        continue
                    title_td = tds[1]
                    a_tag = title_td.find("a")
                    if not a_tag:
                        continue
                    title = a_tag.get_text(strip=True)
                    href = a_tag.get("href","")
                    full_url = "https://judgment.judicial.gov.tw/FJUD/" + href if href.startswith("FLAW") else href
                    date_text = tds[2].get_text(strip=True) if len(tds) > 2 else ""

                    print(f"  {title[:55]}")
                    body = fetch_text(full_url)
                    result = analyze(title, body)
                    row = {
                        "title": title,
                        "court": result.get("court_stage",""),
                        "country": "台灣",
                        "summary": result.get("summary",""),
                        "source_url": full_url,
                        "full_text_url": full_url,
                        "defendant_type": result.get("defendant_type","不明"),
                        "legal_cause": result.get("legal_cause","不明"),
                        "court_stage": result.get("court_stage","不明"),
                        "topic_tags": result.get("topic_tags",[kw]),
                        "tags": ["climate","litigation","case","taiwan"]
                    }
                    status = "NEW" if upsert_case(row) else "UPD"
                    print(f"  {status}: {row['defendant_type']} | {row['legal_cause']}")
                    time.sleep(1)
                except Exception as e:
                    print(f"  row ERR: {e}")
            time.sleep(2)
        except Exception as e:
            print(f"  keyword '{kw}' ERR: {e}")

# ── SOURCE 4: 中國裁判文書網 ────────────────────────

def crawl_china_court():
    print("\n=== 中國裁判文書網 ===")
    keywords = ["气候变化", "碳排放", "温室气体"]
    for kw in keywords:
        try:
            url = f"https://wenshu.court.gov.cn/website/wenshu/181107ANFZ0BXSK4/index.html?pageId=&s8=02&s1={requests.utils.quote(kw)}"
            resp = requests.get(url, headers=HEADERS, timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")
            items = soup.select(".main_content li")[:5]

            for item in items:
                try:
                    a_tag = item.find("a")
                    if not a_tag:
                        continue
                    title = a_tag.get_text(strip=True)
                    href = a_tag.get("href","")
                    full_url = "https://wenshu.court.gov.cn" + href if href.startswith("/") else href

                    print(f"  {title[:55]}")
                    body = fetch_text(full_url)
                    result = analyze(title, body)
                    row = {
                        "title": title,
                        "court": result.get("court_stage",""),
                        "country": "中國",
                        "summary": result.get("summary",""),
                        "source_url": full_url,
                        "full_text_url": full_url,
                        "defendant_type": result.get("defendant_type","不明"),
                        "legal_cause": result.get("legal_cause","不明"),
                        "court_stage": result.get("court_stage","不明"),
                        "topic_tags": result.get("topic_tags",[]),
                        "tags": ["climate","litigation","case","china"]
                    }
                    status = "NEW" if upsert_case(row) else "UPD"
                    print(f"  {status}: {row['defendant_type']} | {row['legal_cause']}")
                    time.sleep(1)
                except Exception as e:
                    print(f"  item ERR: {e}")
            time.sleep(2)
        except Exception as e:
            print(f"  keyword '{kw}' ERR: {e}")

# ── SOURCE 5: ECOLEX ─────────────────────────────────

def crawl_ecolex():
    print("\n=== ECOLEX ===")
    try:
        url = "https://www.ecolex.org/result/?type=CaseAnalysis&q=climate+change&xdate_min=2020-01-01"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        items = soup.select("article.search-result")[:10]

        for item in items:
            try:
                a_tag = item.select_one("h2 a")
                if not a_tag:
                    continue
                title = a_tag.get_text(strip=True)
                href = a_tag.get("href","")
                full_url = "https://www.ecolex.org" + href if href.startswith("/") else href
                excerpt = item.select_one(".search-result-excerpt")
                body = excerpt.get_text(strip=True) if excerpt else ""
                if len(body) < 100:
                    body = fetch_text(full_url)

                print(f"  {title[:55]}")
                result = analyze(title, body)
                row = {
                    "title": title,
                    "court": result.get("court_stage",""),
                    "country": "",
                    "summary": result.get("summary",""),
                    "source_url": full_url,
                    "full_text_url": full_url,
                    "defendant_type": result.get("defendant_type","不明"),
                    "legal_cause": result.get("legal_cause","不明"),
                    "court_stage": result.get("court_stage","不明"),
                    "topic_tags": result.get("topic_tags",[]),
                    "tags": ["climate","litigation","case","ecolex"]
                }
                status = "NEW" if upsert_case(row) else "UPD"
                print(f"  {status}: {row['defendant_type']} | {row['legal_cause']}")
                time.sleep(1)
            except Exception as e:
                print(f"  item ERR: {e}")
    except Exception as e:
        print(f"  ECOLEX ERR: {e}")

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

# ── MAIN ──────────────────────────────────────────────

if __name__ == "__main__":
    print("Starting crawl...")
    crawl_google_news()
    crawl_sabin()
    crawl_taiwan_court()
    crawl_china_court()
    crawl_ecolex()
    write_email_body()
    print("\nAll done.")
