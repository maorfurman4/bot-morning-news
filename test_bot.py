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
assert bot.fmt_market("S&P", "index", 7663.43, 7757.3).endswith("▼ 1.21%")
assert "▲ 5 נ\"ב" in bot.fmt_market("10Y", "yield", 4.95, 4.90)

# פריט עם id שלא קיים (המצאה של ה-AI) לא מוצג; הקישור מגיע מהנתונים
bot.register("w", kept)
assert bot.bullets([{"id": "w1", "text": "א"}, {"id": "w99", "text": "ב"}]) == [
    '• א — <a href="https://x/1">Reuters</a>'
]

# פיצול הודעות ארוכות
parts = bot.chunks(["x" * 2000, "y" * 2000, "z" * 100])
assert len(parts) == 2 and all(len(p) <= 3900 for p in parts)

print("ok")
