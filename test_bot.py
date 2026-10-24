"""בדיקות קצרות: python test_bot.py"""
from datetime import datetime, timezone

import bot

now = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)

# Google News: שם המקור נחתך מהכותרת, כתבה ישנה ומקור לא אמין מסוננים, הסדר נשמר
XML = b"""<rss><channel>
<item><title>Tesla falls 5% - Reuters</title><link>https://x/1</link><source url="https://reuters.com">Reuters</source>
<pubDate>Fri, 23 Oct 2026 08:00:00 GMT</pubDate><description>&lt;b&gt;sales&lt;/b&gt; miss</description></item>
<item><title>Old story - Reuters</title><link>https://x/2</link><source url="https://reuters.com">Reuters</source>
<pubDate>Mon, 19 Oct 2026 08:00:00 GMT</pubDate></item>
<item><title>Some blog - RandomBlog</title><link>https://x/3</link><source url="https://b.com">RandomBlog</source>
<pubDate>Fri, 23 Oct 2026 09:00:00 GMT</pubDate></item>
<item><title>Iran talks - BBC</title><link>https://x/4</link><source url="https://bbc.com">BBC</source>
<pubDate>Fri, 23 Oct 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""
items = bot.parse_rss(XML)
assert items[0]["title"] == "Tesla falls 5%" and items[0]["summary"] == "sales miss"
kept = bot.fresh([i for i in items if bot.trusted(i["source"])], now)
assert [i["link"] for i in kept] == ["https://x/1", "https://x/4"]
assert not bot.trusted("James Martin Center for Nonproliferation Studies")
assert bot.trusted("Bloomberg.com") and bot.trusted("גלובס") and bot.trusted("The Times of Israel")

# Atom (The Verge)
ATOM = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>New robot</title>
<link rel="alternate" href="https://v/1"/><published>2026-10-23T09:00:00-04:00</published>
<summary>Walks &amp; talks</summary></entry></feed>"""
a = bot.parse_rss(ATOM, "The Verge")
assert a[0]["link"] == "https://v/1" and a[0]["source"] == "The Verge" and a[0]["summary"] == "Walks & talks"

# חיסכון בטוקנים: תקציר עד 200 תווים, ותקציר שרק חוזר על הכותרת (Google News) לא נשלח ל-AI
long = bot.parse_rss(b"<rss><channel><item><title>T</title><link>https://x/9</link><pubDate>Fri, 23 Oct 2026 08:00:00 GMT</pubDate>"
                     b"<description>" + b"a" * 900 + b"</description></item></channel></rss>", "BBC")
assert len(long[0]["summary"]) == 200
dup = {"title": "Intel rises 3%", "summary": "Intel rises 3%  Reuters", "source": "Reuters", "link": "l", "published": now}
own = {"title": "Rain in Tel Aviv", "summary": "Heavy rain expected tomorrow", "source": "BBC", "link": "l", "published": now}
sent = bot.register("z", [dup, own])
assert "summary" not in sent[0] and sent[1]["summary"] == "Heavy rain expected tomorrow"
assert bot.MODELS[0] == "gpt-5-mini"

# פורמט שוק
assert bot.fmt_market("נאסד\"ק", "index", 7663.43, 7757.3).endswith("ירידה של 1.21%")
assert "עלייה של 5 נ\"ב" in bot.fmt_market("10Y", "yield", 4.95, 4.90)
assert bot.fmt_holding("MBLY", {"last": 6.55, "pct": -5.7}).startswith("🔥 מובילאיי (MBLY)")

# הקישור תמיד של הכתבה שהפריט באמת מבוסס עליה
bot.register("w", kept)
good = {"id": "w1", "source_title": "Tesla falls 5%", "emoji": "🚗", "title": "א", "bottom_line": "ב"}
assert bot.article(good) == (
    '🔻 <b>🚗 א</b>\n💡 <i>השורה התחתונה:</i> ב\n🔗 <a href="https://x/1">לקריאת הכתבה המלאה</a> · Reuters'
)
mixed = dict(good, id="w2")  # ה-AI התבלבל ב-id — מתוקן לפי source_title
assert 'href="https://x/1"' in bot.article(mixed)
assert bot.article(dict(good, source_title="המצאה")) == ""  # אין כתבה כזו — לא מוצג
assert "🔗" not in bot.article({"id": None, "title": "MBLY", "bottom_line": "אין סיבה"}, need_id=False)

# פיצול הודעות ארוכות; כל שורה מתחילה בתו כיוון מימין לשמאל
parts = bot.chunks(["x" * 2000, "y" * 2000, "z\nOpenAI"])
assert len(parts) == 2 and all(len(p) <= 3900 for p in parts)
assert all(line.startswith(bot.RLM) for line in parts[1].split("\n") if line)

# הודעה נפרדת לכל נושא; נושא בלי כתבות לא נשלח; הפתיח רק בהודעה הראשונה
msgs = bot.render(now, [], None, {}, {"israel": [good], "ai": [dict(good, source_title="x")], "world": [good]})
assert len(msgs) == 2 and msgs[0][1].startswith("🇮🇱") and msgs[1][0].startswith("🌍")
assert msgs[0][0].startswith("🌅")

print("ok")
