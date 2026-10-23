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

# (סימול, שם, סוג) — הסוג קובע איך מציגים את השינוי. שמות בעברית כדי שהשורה תישאר מימין לשמאל
MARKETS = [
    ("^GSPC", "אס אנד פי 500", "index"),
    ("^IXIC", "נאסד\"ק", "index"),
    ("^DJI", "דאו ג'ונס", "index"),
    ("TA35.TA", "ת\"א-35", "index"),
    ("^VIX", "מדד הפחד (VIX)", "index"),
    ("^TNX", "אג\"ח ארה\"ב 10 שנים", "yield"),
    ("ILS=X", "דולר/שקל", "fx"),
    ("BZ=F", "נפט ברנט", "usd"),
]

# המניות שלי: סימול → (שם לחיפוש חדשות, שם בעברית)
HOLDINGS = {
    "INTC": ("Intel", "אינטל"),
    "MBLY": ("Mobileye", "מובילאיי"),
    "TSLA": ("Tesla", "טסלה"),
    "SPCX": ("SpaceX", "ספייס אקס"),
    "TEVA": ("Teva", "טבע"),
    "NVO": ("Novo Nordisk", "נובו נורדיסק"),
    "QBTS": ("D-Wave Quantum", "די-וייב"),
    "AMZN": ("Amazon", "אמזון"),
    "GOOG": ("Alphabet", "גוגל"),
}

FEEDS = {
    "israel": [
        ("גלובס", "https://www.globes.co.il/webservice/rss/rssfeeder.asmx/FeederNode?iID=2"),
        ("ynet", "https://www.ynet.co.il/Integration/StoryRss2.xml"),
        # ה-RSS שלהם חוסם את שרתי GitHub (403), אז דרך Google News
        ("Times of Israel", "https://news.google.com/rss/search?q=site:timesofisrael.com+when:1d&hl=en-US&gl=US&ceid=US:en"),
    ],
    "ai": [
        ("TechCrunch", "https://techcrunch.com/category/artificial-intelligence/feed/"),
        ("MIT Technology Review", "https://www.technologyreview.com/topic/artificial-intelligence/feed"),
    ],
    "tech": [
        ("BBC", "https://feeds.bbci.co.uk/news/technology/rss.xml"),
        ("TechCrunch", "https://techcrunch.com/category/robotics/feed/"),
        ("IEEE Spectrum", "https://spectrum.ieee.org/feeds/topic/robotics.rss"),
    ],
    "world": [
        ("BBC", "https://feeds.bbci.co.uk/news/world/rss.xml"),
        ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
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
RLM = "‏"  # תו כיוון: שורה שמתחילה באנגלית (OpenAI, S&P) לא תתהפך לשמאל-לימין

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

def move(up: bool, amount: str) -> str:
    return f"{'עלייה' if up else 'ירידה'} של {amount}"

def fmt_market(name: str, kind: str, last: float, prev: float) -> str:
    up = last >= prev
    icon = "🟢" if up else "🔴"
    if kind == "yield":
        return f"{icon} {name}: <b>{last:.2f}%</b> | {move(up, f'{abs(last - prev) * 100:.0f} נ\"ב')}"
    value = {"fx": f"{last:.3f} ₪", "usd": f"{last:.2f} דולר"}.get(kind, f"{last:,.2f}" if last < 100 else f"{last:,.0f}")
    return f"{icon} {name}: <b>{value}</b> | {move(up, f'{abs((last - prev) / prev * 100):.2f}%')}"

def get_markets() -> tuple:
    rows, close_date = [], None
    for symbol, name, kind in MARKETS:
        try:
            last, prev, day = quote(symbol)
        except Exception as ex:
            fail(f"שוק {name}", ex)
            continue
        close_date = close_date or day
        rows.append(fmt_market(name, kind, last, prev))
    return rows, close_date

def get_holdings() -> dict:
    out = {}
    for ticker in HOLDINGS:
        try:
            last, prev, _ = quote(ticker)
            out[ticker] = {"last": last, "pct": (last - prev) / prev * 100}
        except Exception as ex:
            fail(f"מניה {ticker}", ex)
    return out

def fmt_holding(ticker: str, q: dict) -> str:
    up = q["pct"] >= 0
    icon = "🔥" if abs(q["pct"]) >= DRAMATIC else "🟢" if up else "🔴"
    return f"{icon} {HOLDINGS[ticker][1]} ({ticker}): <b>{q['last']:.2f} דולר</b> | {move(up, f'{abs(q['pct']):.1f}%')}"

# =============================================================================
# ─── סיכום AI ────────────────────────────────────────────────────────────────
# =============================================================================

PROMPT = """
אתה "סוכן אנליסט" אישי ויוקרתי שכותב בריף בוקר למאור — משקיע פרטי שרוצה להבין מה קרה ולמה זה חשוב.

כללי ברזל:
1. השתמש אך ורק בכתבות שקיבלת (לפי id) ובמספרים שקיבלת. אסור להמציא עובדות, מספרים או סיבות.
2. הכל בעברית עסקית וזורמת. שם חברה באנגלית מותר בתוך משפט, לא בתחילתו.
3. title — כותרת מושכת וקצרה. bottom_line — 2 שורות: מה קרה, ולמה זה חשוב / מה המשמעות.
4. אל תחזור על אותו סיפור בשני מדורים. כל מדור נשלח כהודעה נפרדת: הכנס בו את כל הידיעות הקריטיות
   והמשמעותיות (3 עד 6), לפי סדר חשיבות. לא למלא ברכילות או בידיעות שוליות רק כדי להגיע למספר.
5. אם אין כתבה שמסבירה תזוזה של מניה — כתוב "אין סיבה מדווחת בכתבות מהיממה האחרונה" ואל תנחש.

החזר JSON בלבד במבנה:
{
  "israel": [{"id": "...", "emoji": "🛡️", "title": "...", "bottom_line": "..."}],   // ישראל — ביטחון, פוליטיקה, כלכלה
  "ai":     [{"id": "...", "emoji": "...", "title": "...", "bottom_line": "..."}],    // בינה מלאכותית
  "tech":   [{"id": "...", "emoji": "...", "title": "...", "bottom_line": "..."}],    // טכנולוגיה ורובוטיקה (לא AI)
  "world":  [{"id": "...", "emoji": "...", "title": "...", "bottom_line": "..."}],    // אקטואליה עולמית וכלכלה
  "market_why": [{"text": "...", "ids": ["..."]}],    // 2-3 משפטים: מה זז באמת בשווקים ולמה (מספרים מ-markets + כתבות market)
  "companies": [{"ticker": "...", "id": "... או null", "emoji": "...", "title": "...", "bottom_line": "..."}]
      // חובה פריט לכל מניה עם dramatic=true; ועוד כל ידיעה משמעותית על המניות שלי
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
# ─── בניית ההודעה (העיצוב המקורי של הבריף) ───────────────────────────────────
# =============================================================================

def article(e: dict, need_id: bool = True) -> str:
    item = ITEMS.get(e.get("id"))
    if not e.get("title") or not e.get("bottom_line") or (need_id and not item):
        return ""  # פריט בלי כתבה אמיתית מאחוריו — לא מציגים
    out = f"🔻 <b>{esc(e.get('emoji', ''))} {esc(e['title'])}</b>\n💡 <i>השורה התחתונה:</i> {esc(e['bottom_line'])}"
    if item:
        out += f"\n🔗 <a href=\"{esc(item['link'])}\">לקריאת הכתבה המלאה</a> · {esc(item['source'])}"
    return out

def render(today: datetime, market_rows: list, close_date, holdings: dict, ai: dict) -> list:
    """רשימת הודעות — הודעה לכל נושא; כל הודעה היא כותרת + בלוקים."""
    why = []
    for w in ai.get("market_why") or []:
        src = " · ".join(f'<a href="{esc(ITEMS[i]["link"])}">{esc(ITEMS[i]["source"])}</a>' for i in w.get("ids") or [] if i in ITEMS)
        if w.get("text"):
            why.append(f"• {esc(w['text'])}" + (f" ({src})" if src else ""))

    stocks = [
        "📊 <b>מצב השוק</b>" + (f" <i>(סגירה {close_date:%d/%m})</i>" if close_date else "") + "\n" + "\n".join(market_rows)
        if market_rows else "",
        "💡 <b>מה זז באמת:</b>\n" + "\n".join(why) if why else "",
        "💼 <b>המניות שלי</b>\n" + "\n".join(
            fmt_holding(t, q) for t, q in sorted(holdings.items(), key=lambda kv: abs(kv[1]["pct"]), reverse=True)
        ) if holdings else "",
        *[article(c, need_id=False) for c in ai.get("companies") or []],
    ]

    date = f"<i>{today:%d/%m/%Y}</i>"
    topics = [
        (f"🇮🇱 <b>ישראל</b> · {date}", [article(e) for e in ai.get("israel") or []]),
        (f"🤖 <b>בינה מלאכותית (AI)</b> · {date}", [article(e) for e in ai.get("ai") or []]),
        (f"🦾 <b>טכנולוגיה ורובוטיקה</b> · {date}", [article(e) for e in ai.get("tech") or []]),
        (f"🌍 <b>אקטואליה עולמית</b> · {date}", [article(e) for e in ai.get("world") or []]),
        (f"📈 <b>שוק ההון ותיק המניות</b> · {date}", stocks),
        ("⚠️ <b>בוט החדשות — מה לא עבד היום:</b>", ["\n".join(FAILURES)] if FAILURES else []),
    ]
    messages = [[title, SEP, *[b for b in blocks if b]] for title, blocks in topics if any(blocks)]
    if messages:
        messages[0].insert(0, f"🌅 <b>בוקר טוב מאור — בריף בוקר</b> ☕")
    return messages

def rtl(text: str) -> str:
    return "\n".join(RLM + line if line else line for line in text.split("\n"))

def chunks(blocks: list, limit: int = 3900) -> list:
    """הודעה אחת לנושא; רק אם היא ארוכה מהמותר בטלגרם — מפוצלת בין כתבות."""
    # shortcut: בלוק בודד ארוך מ-4096 תווים עדיין ייכשל; לפצל לפי שורות אם זה יקרה
    out, cur = [], ""
    for b in blocks:
        if cur and len(cur) + len(b) + 2 > limit:
            out.append(cur)
            cur = b
        else:
            cur = f"{cur}\n\n{b}" if cur else b
    return [rtl(c) for c in (out + [cur] if cur else out)]

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
    market_rows, close_date = get_markets()
    holdings = get_holdings()

    print("📥 News...")
    news = {cat: register(cat[0], get_feed(cat, now)) for cat in FEEDS}
    market_news = fresh([i for q in MARKET_QUERIES for i in gnews(q, now)], now)[:12]
    news["market"] = register("m", market_news)
    news["holdings"] = {t: register(f"h{t}_", gnews(f'"{name}" stock', now, 4)) for t, (name, _) in HOLDINGS.items()}

    payload = {
        "markets": [re.sub(r"<[^>]+>", "", r) for r in market_rows],
        "holdings": [
            {"ticker": t, "name": HOLDINGS[t][0], "change_pct": round(q["pct"], 2), "dramatic": abs(q["pct"]) >= DRAMATIC}
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
    return [part for msg in render(now.astimezone(IL_TZ), market_rows, close_date, holdings, ai) for part in chunks(msg)]

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
