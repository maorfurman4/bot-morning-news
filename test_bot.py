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
assert bot.gn_ok("YNET") and not bot.gn_ok("מעריב") and not bot.gn_ok("Maariv")  # תאריכים הפוכים ב-Google News

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
assert bot.register("y", [own], now + bot.timedelta(hours=5))[0]["age_hours"] == 5  # ה-AI יודע כמה הכתבה טרייה
assert bot.MODELS[0] == "gpt-5-mini"

# פורמט שוק
assert bot.fmt_market("Nasdaq", "index", 7663.43, 7757.3) == "🔴 Nasdaq     7,663  ▼1.21%"
assert bot.fmt_market("US 10Y", "yield", 4.95, 4.90).endswith("4.95%  ▲5bp")
assert bot.fmt_market("S&P 500", "index", 7744, 7722).startswith("🟢 S&amp;P 500    7,744")  # יישור לפי האורך הנראה
assert bot.fmt_holding("MBLY", {"last": 6.55, "pct": -5.7}).startswith("🔥 מובילאיי (MBLY)")

# הקישור תמיד של הכתבה שהפריט באמת מבוסס עליה
bot.register("w", kept)
good = {"id": "w1", "source_title": "Tesla falls 5%", "emoji": "🚗", "title": "א", "bottom_line": "ב"}
assert bot.article(good) == (
    '🔹 <b>🚗 א</b>\n💡 <i>השורה התחתונה:</i> ב\n🔗 <a href="https://x/1">לקריאת הכתבה המלאה</a> · Reuters'
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
msgs, _ = bot.render(now, [], None, {}, {"israel": [good], "ai": [dict(good, source_title="x")], "world": [good]})
assert len(msgs) == 2 and msgs[0][1].startswith("🇮🇱") and msgs[1][0].startswith("🌍")
assert msgs[0][0].startswith("🌅")

# 📢 ערוץ: בריף כללי בלבד. המניות שלך ודוח התקלות — רק אליך בפרטי
bot.FAILURES.append("• <b>מקור X</b>: 403")
hold = {"MBLY": {"last": 6.55, "pct": -5.7}}
pub, priv = bot.render(now, ['🔴 נאסד"ק: <b>26,001</b>'], None, hold, {"israel": [good]}, channel=True)
public_text, private_text = "\n".join(sum(pub, [])), "\n".join(sum(priv, []))
assert "מאור" not in public_text and "מובילאיי" not in public_text and "מה לא עבד" not in public_text
assert "נאסד\"ק" in public_text and pub[0][0] == "🌅 <b>בוקר טוב — בריף בוקר</b> ☕"
assert "מובילאיי" in private_text and "מה לא עבד" in private_text
_, priv_only = bot.render(now, [], None, hold, {}, channel=False)
assert "מובילאיי" in "\n".join(sum(priv_only, []))
# 📈 שוק ההון בערוץ: גם "על מה לשים לב" וידיעות שוק — ידיעות על המניות שלך נשארות בפרטי
ai = {"watch": [{"text": "החלטת ריבית בארה\"ב ביום רביעי", "ids": ["w1"]}],
      "market_news": [dict(good, id="w2", source_title="Iran talks", title="וול סטריט ירדה")],
      "companies": [dict(good, title="מובילאיי צנחה")]}
pub, priv = bot.render(now, ['🔴 נאסד"ק: <b>26,001</b>'], None, hold, ai, channel=True)
public_text, private_text = "\n".join(sum(pub, [])), "\n".join(sum(priv, []))
assert "על מה לשים לב" in public_text and "החלטת ריבית" in public_text and "וול סטריט ירדה" in public_text
assert "מובילאיי צנחה" not in public_text and "מובילאיי צנחה" in private_text
# סיפור שכבר הוזכר ב"מה זז"/"על מה לשים לב" לא חוזר כידיעה נפרדת; מקור בלי סוגריים
dup_ai = {"watch": [{"text": "ריבית", "ids": ["w1"]}], "market_news": [dict(good, title="כפול")]}
pub, _ = bot.render(now, [], None, {}, dup_ai, channel=True)
text = "\n".join(sum(pub, []))
assert "כפול" not in text and text.count('href="https://x/1"') == 1 and "📚" in text  # מקור פעם אחת, בשורת המקורות
# 5 ידיעות לכל היותר בנושא; טבלת השוק בלי תווי כיוון בתוכה
eight = bot.register("v", [dict(own, title=f"story {n}", link=f"https://v/{n}") for n in range(8)])
msgs, _ = bot.render(now, ["🟢 a", "🔴 b"], None, {}, {"world": [dict(good, id=e["id"], source_title=e["title"]) for e in eight]})
assert sum(b.startswith("🔹") for b in msgs[0]) == 5
table = bot.chunks(next(m for m in bot.render(now, ["🟢 a", "🔴 b"], None, {}, {})[0]))[0]
assert "\n🔴 b</pre>" in table

# 🕵️ רכישות פנים: רק קניות, רק בכירים, רק מהיממה האחרונה, בלי SPAC; ממוין לפי סכום
row = lambda filed, tk, co, role, typ, val: (f"<tr><td></td><td>{filed}</td><td>x</td><td><a>{tk}</a></td><td>{co}</td>"
                                            f"<td>N</td><td>{role}</td><td>{typ}</td><td>$10.00</td><td></td><td></td><td></td><td>{val}</td></tr>")
page = '<table class="tinytable"><tr><th>h</th></tr>' + "".join([
    row("2026-10-23 07:00:00", "AAA", "Alpha Inc /DE", "CEO", "P - Purchase", "+$250,000"),
    row("2026-10-23 06:00:00", "BBB", "Beta Corp", "Dir", "P - Purchase", "+$1,500,000"),
    row("2026-10-23 06:00:00", "CCC", "Gamma Acquisition Co", "CEO", "P - Purchase", "+$9,000,000"),  # SPAC
    row("2026-10-23 06:00:00", "DDD", "Delta", "10%", "P - Purchase", "+$9,000,000"),  # לא בכיר
    row("2026-10-20 06:00:00", "EEE", "Epsilon", "CEO", "P - Purchase", "+$9,000,000"),  # ישן
    row("2026-10-23 06:00:00", "FFF", "Phi", "CEO", "S - Sale", "-$9,000,000"),  # מכירה
]) + "</table>"
ins = bot.parse_insiders(page, now)
assert [i["ticker"] for i in ins] == ["BBB", "AAA"] and ins[1]["company"] == "Alpha Inc"
assert bot.fmt_insider(ins[0]).endswith('— דירקטור קנה ב-<b>$1.5M</b>, במחיר $10.00')
pub, _ = bot.render(now, ["🟢 a"], None, {}, {}, channel=True, insiders=ins)
assert "🕵️ <b>רכישות פנים</b>" in "\n".join(sum(pub, []))

# חיבור שנפל מול OpenAI → עוברים למודל הבא במקום לאבד נושא שלם (קרה 06/11/2026)
class Ok:
    ok = True
    def json(self):
        return {"choices": [{"message": {"content": '{"items": []}'}}]}
tries = [bot.requests.ConnectionError("dropped"), Ok()]
def fake_post(*a, **k):
    r = tries.pop(0)
    if isinstance(r, Exception):
        raise r
    return r
real_post, bot.requests.post = bot.requests.post, fake_post
assert bot.ask_ai("s", {}) == {"items": []} and not tries
bot.requests.post = real_post

# 📺 בלוק "אמש" בראש הבידור/ספורט; שורה בלי כתבה אמיתית לא מוצגת; ריק → אין בלוק
msgs, _ = bot.render(now, [], None, {}, {"ent": [good], "ent_recap": [
    {"label": "האח הגדול", "text": "ענבל אלדן הודחה", "ids": ["w1"]}, {"label": "המצאה", "text": "x", "ids": ["zz"]}]})
ent = next(m for m in msgs if "בידור" in m[0] or "בידור" in m[1])
assert any(b.startswith("📺 <b>אמש בריאליטי</b>\n• <b>האח הגדול</b> — ענבל אלדן הודחה") for b in ent)
assert "המצאה" not in "\n".join(ent)
msgs, _ = bot.render(now, [], None, {}, {"sport": [good], "sport_recap": []})
assert not any("🏟️" in b for b in sum(msgs, []))

# ידיעה על כתבה שכבר בבלוק "אמש" לא חוזרת — עוברים לבאה בתור; ספורט/בידור בפורמט קליל
iran = dict(good, id="w2", source_title="Iran talks", title="שיחות")
blocks = bot.topic_blocks("sport", {"sport": [good, iran], "sport_recap": [{"label": "יורוליג", "text": "x", "ids": ["w1"]}]})
assert blocks[0].startswith("🏟️") and len(blocks) == 2 and "שיחות" in blocks[1] and "השורה התחתונה" not in blocks[1]
assert "השורה התחתונה" in bot.topic_blocks("israel", {"israel": [good]})[1]
assert len(bot.topic_blocks("world", {"world": [good] * 9})) == 2  # אותה כתבה פעמיים — פעם אחת

# כמה מקורות מספרים את אותו סיפור
same = [{"title": "ענבל אלדן הודחה מהאח הגדול", "source": "YNET"}, {"title": "דיירת האח הגדול ענבל אלדן הודחה", "source": "mako"},
        {"title": "מכבי ניצחה את הפועל", "source": "YNET"}]
assert bot.coverage(same) == [2, 2, 1]
# 🗓️ כתבה שה-AI בחר והתאריך שבה ישן — נזרקת (גם מבלוק "אמש"); אי אפשר לדעת — נשארת
assert bot.real_url("https://www.ynet.co.il/a") == "https://www.ynet.co.il/a"
old_story = dict(own, title="June story", link="https://news.google.com/rss/articles/OLD")
reg = bot.register("q", [old_story])
ai = {"ent": [dict(good, id=reg[0]["id"], source_title="June story"), good], "ent_recap": [{"label": "x", "text": "y", "ids": [reg[0]["id"]]}]}
real_date, bot.real_date = bot.real_date, lambda link: now - bot.timedelta(days=148) if "OLD" in link else None
bot.drop_stale(ai, bot.stale_links(ai, now))
bot.real_date = real_date
assert [e["title"] for e in ai["ent"]] == ["א"] and ai["ent_recap"][0]["ids"] == []

# 🏟️ תוצאה רשמית: תמיד ראשונה בבלוק, בקוד, עם שמות עבריים לקבוצות ישראליות; בלי דגלים באימוג'י
res = [{"comp": "יורוליג", "game": "Hapoel IBI Tel Aviv 90-93 FC Barcelona"}]
block = bot.recap_block("sport", [{"label": "x", "text": "המצאה", "ids": ["zz"]}], res)
assert block == '🏟️ <b>אמש במגרשים</b>\n• <b>יורוליג</b> — הפועל ת&quot;א 90:93 FC Barcelona'
assert bot.recap_block("sport", [], []) == ""
dup = bot.recap_block("sport", [{"label": "יורוליג", "text": "Hapoel 90-93 Barcelona — הפסד שני", "ids": ["w1"]}], res)
assert dup.count("•") == 1  # השורה של ה-AI על אותו משחק לא מוצגת
assert "🇮🇱" not in bot.article(dict(good, emoji="🇮🇱"))

# ✍️ עורך שני: מתקן ניסוח, מוריד כפילות; נכשל — הטקסט המקורי נשאר
ai = {"ent": [dict(good, id="w1", bottom_line="YNET חשף: א"), dict(good, id="w2", title="כפול")],
      "ent_recap": [{"label": "האח הגדול", "text": "x", "ids": ["w1"]}]}
real_ask, bot.ask_ai = bot.ask_ai, lambda s, p: {"topics": [{"key": "ent", "items": [
    {"id": "w1", "title": "א", "bottom_line": "א נקי"}, {"id": "w2", "drop": True}], "recap": [{"n": 0, "text": "y"}]}]}
bot.edit_pass(ai)
assert [e["bottom_line"] for e in ai["ent"]] == ["א נקי"] and ai["ent_recap"][0]["text"] == "y"
def boom(s, p):
    raise RuntimeError("down")
bot.ask_ai = boom
bot.edit_pass(ai)
assert ai["ent"][0]["bottom_line"] == "א נקי" and bot.FAILURES[-1].startswith("• <b>עורך")
bot.ask_ai = real_ask
bot.FAILURES.clear()

print("ok")
