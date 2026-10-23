#!/usr/bin/env python3
"""
בריף חדשות בוקר — נתוני שוק אמיתיים + חדשות ממקורות אמינים, מסוכמים בעברית.
המספרים מחושבים בקוד; GPT רק בוחר, מתרגם ומסביר — ורק מתוך הכתבות שקיבל.
הרצה מקומית בלי שליחה: python bot.py --dry-run
"""

import html
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import requests
import yfinance as yf

# =============================================================================
# ─── הגדרות וסודות ───────────────────────────────────────────────────────────
# =============================================================================
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN_NEWS", "").strip()
CHAT_ID = os.environ.get("CHAT_ID_NEWS", "").strip()

IL_TZ = ZoneInfo("Asia/Jerusalem")
MAX_AGE = timedelta(hours=26)
DRAMATIC = 3.0  # % — מניה שזזה יותר מזה מקבלת הסבר

# (סימול, שם, סוג) — הסוג קובע איך מציגים את השינוי
MARKETS = [
    ("^GSPC", "S&P 500", "index"),
    ("^IXIC", "נאסד\"ק", "index"),
    ("^DJI", "דאו ג'ונס", "index"),
    ("TA35.TA", "ת\"א-35", "index"),
    ("^VIX", "VIX (מדד הפחד)", "index"),
    ("^TNX", "אג\"ח ארה\"ב 10 שנים", "yield"),
    ("ILS=X", "דולר/שקל", "fx"),
    ("BZ=F", "נפט ברנט", "usd"),
]

# המניות שלי — השם משמש לחיפוש חדשות
HOLDINGS = {
    "INTC": "Intel", "MBLY": "Mobileye", "TSLA": "Tesla", "SPCX": "SpaceX", "TEVA": "Teva",
    "NVO": "Novo Nordisk", "QBTS": "D-Wave Quantum", "AMZN": "Amazon", "GOOG": "Alphabet",
}

FEEDS = {
    "israel": [
        ("גלובס", "https://www.globes.co.il/webservice/rss/rssfeeder.asmx/FeederNode?iID=2"),
        ("ynet", "https://www.ynet.co.il/Integration/StoryRss2.xml"),
        ("Times of Israel", "https://www.timesofisrael.com/feed/"),
    ],
    "world": [("BBC", "https://feeds.bbci.co.uk/news/world/rss.xml")],
    "business": [
        ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
        ("CNBC", "https://www.cnbc.com/id/10000664/device/rss/rss.html"),
    ],
    "tech": [
        ("TechCrunch", "https://techcrunch.com/category/artificial-intelligence/feed/"),
        ("BBC", "https://feeds.bbci.co.uk/news/technology/rss.xml"),
    ],
}

MARKET_QUERIES = ["stock market today", "Wall Street stocks close", "Tel Aviv Stock Exchange"]

# מתוצאות Google News נשארות רק כתבות ממקורות אלה
TRUSTED = (
    "reuters", "bloomberg", "cnbc", "wall street journal", "wsj", "marketwatch", "yahoo",
    "financial times", "barron", "ap news", "associated press", "investing.com", "axios",
    "techcrunch", "the verge", "fortune", "business insider", "times of israel",
    "globes", "calcalist", "themarker", "גלובס", "כלכליסט", "דה מרקר",
)

SEP = "〰️〰️〰️〰️〰️〰️〰️〰️〰️〰️"

def esc(text) -> str:
    return html.escape(str(text))

# ── דוח כשלונות — מצורף לסוף הבריף כדי שנדע מה לתקן ───────────────────────────

FAILURES = []

def fail(section: str, ex) -> None:
    print(f"❌ {section}: {ex}")
    # בלי כתובות — כתובת טלגרם מכילה את הטוקן
    detail = re.sub(r"https?://\S+", "<url>", str(ex))[:150]
    FAILURES.append(f"• <b>{esc(section)}</b>: {esc(detail)}")

# =============================================================================
# ─── חדשות: RSS ממקורות קבועים + Google News מסונן ───────────────────────────
# =============================================================================

def fetch(url: str) -> bytes:
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    resp.raise_for_status()
    return resp.content

def parse_rss(content: bytes, source: str | None = None) -> list:
    """source=None: שם המקור נלקח מכל כתבה (Google News)."""
    items = []
    for it in ET.fromstring(content).iter("item"):
        title = (it.findtext("title") or "").strip()
        src = source or (it.findtext("source") or "").strip()
        if source is None and src and title.endswith(f" - {src}"):
            title = title[: -len(src) - 3]
        try:
            published = parsedate_to_datetime((it.findtext("pubDate") or "").strip())
        except (TypeError, ValueError):
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        summary = html.unescape(re.sub(r"<[^>]+>", "", it.findtext("description") or "")).strip()
        items.append({
            "title": html.unescape(title), "link": (it.findtext("link") or "").strip(),
            "source": src, "published": published, "summary": summary[:300],
        })
    return items

def fresh(items: list, now: datetime) -> list:
    seen, out = set(), []
    for i in sorted(items, key=lambda i: i["published"], reverse=True):
        if now - i["published"] <= MAX_AGE and i["title"] and i["title"] not in seen:
            seen.add(i["title"])
            out.append(i)
    return out

def get_feed(category: str, now: datetime, limit: int = 15) -> list:
    items = []
    for name, url in FEEDS[category]:
        try:
            items += parse_rss(fetch(url), name)
        except Exception as ex:
            fail(f"מקור {name}", ex)
    return fresh(items, now)[:limit]

def trusted(source: str) -> bool:
    s = source.lower()
    return any(t in s for t in TRUSTED)

def gnews(query: str, now: datetime, limit: int = 6) -> list:
    url = f"https://news.google.com/rss/search?q={quote_plus(query + ' when:1d')}&hl=en-US&gl=US&ceid=US:en"
    try:
        items = parse_rss(fetch(url))
    except Exception as ex:
        fail(f"Google News ({query})", ex)
        return []
    return fresh([i for i in items if trusted(i["source"])], now)[:limit]

# =============================================================================
# ─── נתוני שוק (Yahoo Finance) ───────────────────────────────────────────────
# =============================================================================

def quote(symbol: str) -> tuple:
    closes = yf.Ticker(symbol).history(period="7d")["Close"].dropna()
    if len(closes) < 2:
        raise ValueError("אין מספיק נתונים")
    return float(closes.iloc[-1]), float(closes.iloc[-2]), closes.index[-1].date()

def fmt_market(name: str, kind: str, last: float, prev: float) -> str:
    pct = (last - prev) / prev * 100
    arrow = "▲" if last >= prev else "▼"
    if kind == "yield":
        return f"{name}: <b>{last:.2f}%</b> {arrow} {abs(last - prev) * 100:.0f} נ\"ב"
    value = {"fx": f"{last:.3f} ₪", "usd": f"${last:.2f}"}.get(kind, f"{last:,.2f}" if last < 100 else f"{last:,.0f}")
    return f"{name}: <b>{value}</b> {arrow} {abs(pct):.2f}%"

def get_markets() -> tuple:
    rows, data, close_date = [], [], None
    for symbol, name, kind in MARKETS:
        try:
            last, prev, day = quote(symbol)
        except Exception as ex:
            fail(f"שוק {name}", ex)
            continue
        close_date = close_date or day
        line = fmt_market(name, kind, last, prev)
        rows.append(line)
        data.append(re.sub(r"<[^>]+>", "", line))
    return rows, data, close_date

def get_holdings() -> dict:
    out = {}
    for ticker in HOLDINGS:
        try:
            last, prev, _ = quote(ticker)
            out[ticker] = {"last": last, "pct": (last - prev) / prev * 100}
        except Exception as ex:
            fail(f"מניה {ticker}", ex)
    return out

# =============================================================================
# ─── סיכום AI ────────────────────────────────────────────────────────────────
# =============================================================================

PROMPT = """
אתה עורך חדשות וכלכלה שכותב בריף בוקר בעברית למאור — משקיע פרטי שרוצה להבין מה קרה ולמה זה חשוב.

כללי ברזל:
1. השתמש אך ורק בכתבות שקיבלת (לפי id) ובמספרים שקיבלת. אסור להמציא עובדות, מספרים או סיבות.
2. כל פריט: משפט או שניים בעברית עסקית וזורמת — מה קרה, ומקף — למה זה חשוב / מה המשמעות.
3. אל תחזור על אותו סיפור בשני מדורים.
4. אם אין כתבה שמסבירה תזוזה — כתוב במפורש "אין סיבה מדווחת בכתבות מהיממה האחרונה". לא לנחש.

החזר JSON בלבד במבנה:
{
  "top":      [{"id": "...", "text": "..."}],            // בדיוק 3 — הסיפורים הכי חשובים של הבוקר מכל המדורים
  "market_why": [{"text": "...", "ids": ["..."]}],       // 2-3 תובנות: מה זז באמת בשווקים ולמה (שילוב המספרים עם כתבות market)
  "holdings": [{"ticker": "...", "text": "...", "ids": ["..."]}],  // לכל מניה dramatic=true, ולכל מניה אחרת שיש עליה ידיעה משמעותית
  "israel":   [{"id": "...", "text": "..."}],            // עד 3
  "world":    [{"id": "...", "text": "..."}],            // עד 4
  "business": [{"id": "...", "text": "..."}],            // עד 3
  "tech":     [{"id": "...", "text": "..."}],            // עד 3 — טכנולוגיה ו-AI
  "deep":     {"id": "...", "text": "..."}               // סיפור אחד לקריאה מעמיקה: 3-4 משפטים — מה קרה, הקשר, למה זה משמעותי
}
"""

ITEMS = {}  # id → כתבה, כדי שהקישורים והמקורות יגיעו מהנתונים ולא מה-AI

def register(prefix: str, items: list) -> list:
    out = []
    for n, i in enumerate(items, 1):
        ITEMS[f"{prefix}{n}"] = i
        out.append({"id": f"{prefix}{n}", "source": i["source"], "title": i["title"], "summary": i["summary"]})
    return out

def summarize(payload: dict) -> dict:
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": "gpt-4o",
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        },
        timeout=180,
    )
    resp.raise_for_status()
    return json.loads(resp.json()["choices"][0]["message"]["content"])

# =============================================================================
# ─── בניית ההודעה ────────────────────────────────────────────────────────────
# =============================================================================

def links(ids) -> str:
    return " · ".join(f'<a href="{esc(ITEMS[i]["link"])}">{esc(ITEMS[i]["source"])}</a>' for i in ids if i in ITEMS)

def bullets(entries, need_id: bool = True) -> list:
    out = []
    for e in entries or []:
        ids = e.get("ids") or ([e["id"]] if e.get("id") else [])
        if not e.get("text") or (need_id and not any(i in ITEMS for i in ids)):
            continue  # פריט בלי כתבה אמיתית מאחוריו — לא מציגים
        src = links(ids)
        out.append(f"• {esc(e['text'])}" + (f" — {src}" if src else ""))
    return out

def section(title: str, lines: list) -> str:
    return f"{title}\n" + "\n".join(lines) if lines else ""

def render(today: datetime, market_rows: list, close_date, holdings: dict, ai: dict) -> list:
    notes = {h.get("ticker"): h for h in ai.get("holdings", [])}
    stock_lines = []
    for t, q in sorted(holdings.items(), key=lambda kv: abs(kv[1]["pct"]), reverse=True):
        icon = "🔥" if abs(q["pct"]) >= DRAMATIC else "▫️"
        line = f"{icon} <b>{t}</b> {'▲' if q['pct'] >= 0 else '▼'} {abs(q['pct']):.1f}% · ${q['last']:.2f}"
        note = bullets([notes[t]], need_id=False) if t in notes else []
        stock_lines.append(line + (f"\n   {note[0][2:]}" if note else ""))

    when = f" <i>(סגירה {close_date:%d/%m})</i>" if close_date else ""
    markets = section(f"📊 <b>תמונת מצב שוקים</b>{when}", market_rows)
    why = bullets(ai.get("market_why"), need_id=False)
    if why:
        markets += "\n\n💡 <b>מה זז באמת</b>\n" + "\n".join(why)

    deep = ai.get("deep") or {}
    deep_text = f"{esc(deep['text'])}\n🔗 {links([deep.get('id')])}" if deep.get("text") and deep.get("id") in ITEMS else ""

    sections = [
        f"☀️ <b>בוקר טוב מאור — בריף בוקר</b> <i>{today:%d.%m.%Y}</i>",
        section("🔝 <b>3 הדברים החשובים הבוקר</b>", bullets(ai.get("top"))),
        markets,
        section("💼 <b>המניות שלי</b>", stock_lines),
        section("🇮🇱 <b>ישראל</b>", bullets(ai.get("israel"))),
        section("🌍 <b>עולם</b>", bullets(ai.get("world"))),
        section("💰 <b>עסקים</b>", bullets(ai.get("business"))),
        section("🤖 <b>טכנולוגיה ו-AI</b>", bullets(ai.get("tech"))),
        section("📖 <b>לקריאה מעמיקה</b>", [deep_text] if deep_text else []),
        section("⚠️ <b>מה לא עבד היום:</b>", FAILURES),
        "<i>שיהיה יום מעולה 🙌</i>",
    ]
    return [s for s in sections if s]

def chunks(sections: list, limit: int = 3900) -> list:
    # shortcut: מדור בודד ארוך מ-4096 תווים עדיין ייכשל; לפצל לפי שורות אם זה יקרה
    out, cur = [], ""
    for s in sections:
        if cur and len(cur) + len(s) + len(SEP) + 4 > limit:
            out.append(cur)
            cur = s
        else:
            cur = f"{cur}\n\n{SEP}\n\n{s}" if cur else s
    return out + [cur] if cur else out

# =============================================================================
# ─── שליחה ───────────────────────────────────────────────────────────────────
# =============================================================================

def send_to_telegram(text: str) -> None:
    resp = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=30,
    )
    if resp.status_code != 200:
        # בלי זה ההרצה ב-Actions מסומנת כהצלחה גם כשההודעה לא הגיעה
        raise RuntimeError(f"Telegram {resp.status_code}: {resp.text[:300]}")

def build() -> list:
    now = datetime.now(timezone.utc)
    print("📊 Market data...")
    market_rows, market_data, close_date = get_markets()
    holdings = get_holdings()

    print("📥 News...")
    news = {cat: register(cat[0], get_feed(cat, now)) for cat in FEEDS}
    market_news = fresh([i for q in MARKET_QUERIES for i in gnews(q, now)], now)[:12]
    news["market"] = register("m", market_news)
    news["holdings"] = {t: register(f"h{t}_", gnews(f'"{name}" stock', now, 4)) for t, name in HOLDINGS.items()}

    payload = {
        "markets": market_data,
        "holdings": [
            {"ticker": t, "name": HOLDINGS[t], "change_pct": round(q["pct"], 2), "dramatic": abs(q["pct"]) >= DRAMATIC}
            for t, q in holdings.items()
        ],
        "news": news,
    }
    print(f"🧠 Summarizing {len(ITEMS)} articles...")
    try:
        ai = summarize(payload)
    except Exception as ex:
        fail("סיכום AI", ex)
        ai = {}
    return chunks(render(now.astimezone(IL_TZ), market_rows, close_date, holdings, ai))

if __name__ == "__main__":
    try:
        messages = build()
    except Exception as ex:
        if "--dry-run" not in sys.argv:
            send_to_telegram(f"⚠️ בוט החדשות נכשל ולא שלח בריף היום:\n{esc(type(ex).__name__)}: {esc(str(ex)[:300])}")
        raise
    for msg in messages:
        if "--dry-run" in sys.argv:
            print(msg, "\n" + "=" * 40)
        else:
            send_to_telegram(msg)
    print("🏁 Run complete.")
