"""בדיקות קצרות: python test_bot.py"""
from datetime import datetime, timezone

import bot

now = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)

# Google News: שם המקור נחתך מהכותרת, כתבה ישנה מסוננת
XML = b"""<rss><channel>
<item><title>Tesla falls 5% - Reuters</title><link>https://x/1</link><source url="https://reuters.com">Reuters</source>
<pubDate>Fri, 23 Oct 2026 08:00:00 GMT</pubDate><description>&lt;b&gt;sales&lt;/b&gt; miss</description></item>
<item><title>Old story - Reuters</title><link>https://x/2</link><source url="https://reuters.com">Reuters</source>
<pubDate>Mon, 19 Oct 2026 08:00:00 GMT</pubDate></item>
<item><title>Some blog - RandomBlog</title><link>https://x/3</link><source url="https://b.com">RandomBlog</source>
<pubDate>Fri, 23 Oct 2026 09:00:00 GMT</pubDate></item>
</channel></rss>"""
items = bot.parse_rss(XML)
assert items[0]["title"] == "Tesla falls 5%" and items[0]["summary"] == "sales miss"
kept = bot.fresh([i for i in items if bot.trusted(i["source"])], now)
assert [i["link"] for i in kept] == ["https://x/1"]

# פורמט שוק
assert bot.fmt_market("נאסד\"ק", "index", 7663.43, 7757.3).endswith("ירידה של 1.21%")
assert "עלייה של 5 נ\"ב" in bot.fmt_market("10Y", "yield", 4.95, 4.90)
assert bot.fmt_holding("MBLY", {"last": 6.55, "pct": -5.7}).startswith("🔥 מובילאיי (MBLY)")

# פריט עם id שלא קיים (המצאה של ה-AI) לא מוצג; הקישור מגיע מהנתונים
bot.register("w", kept)
assert bot.article({"id": "w99", "title": "א", "bottom_line": "ב"}) == ""
assert bot.article({"id": "w1", "emoji": "🚗", "title": "א", "bottom_line": "ב"}) == (
    '🔻 <b>🚗 א</b>\n💡 <i>השורה התחתונה:</i> ב\n🔗 <a href="https://x/1">לקריאת הכתבה המלאה</a> · Reuters'
)

# פיצול הודעות ארוכות; כל שורה מתחילה בתו כיוון מימין לשמאל
parts = bot.chunks(["x" * 2000, "y" * 2000, "z\nOpenAI"])
assert len(parts) == 2 and all(len(p) <= 3900 for p in parts)
assert all(line.startswith(bot.RLM) for line in parts[1].split("\n") if line)

# הודעה נפרדת לכל נושא; נושא בלי כתבות לא נשלח; הפתיח רק בהודעה הראשונה
msgs = bot.render(now, [], None, {}, {
    "israel": [{"id": "w1", "emoji": "🛡️", "title": "א", "bottom_line": "ב"}],
    "ai": [{"id": "w99", "title": "מומצא", "bottom_line": "x"}],
    "world": [{"id": "w1", "emoji": "🌍", "title": "ג", "bottom_line": "ד"}],
})
assert len(msgs) == 2 and msgs[0][1].startswith("🇮🇱") and msgs[1][0].startswith("🌍")
assert msgs[0][0].startswith("🌅")

print("ok")
