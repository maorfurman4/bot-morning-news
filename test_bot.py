"""בדיקות קצרות: python test_bot.py"""
from datetime import datetime, timezone

import bot
import os as _os0, tempfile as _tf0
# הבדיקות הישנות של בלוק הריאליטי משתמשות בכתבות דמה — בלי בדיקת הכותרת ובלי קובץ הזיכרון האמיתי (נבדקים בנפרד למטה)
_real_fit, bot.fact_in_title = bot.fact_in_title, lambda text, title: True
_real_air, bot.after_airing = bot.after_airing, lambda item, label, tv: True
bot.REPORTED_FILE = _os0.path.join(_tf0.mkdtemp(), "none.json")

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
assert bot.gn_ok("YNET") and bot.gn_ok("מעריב")  # מעריב חוזר — התאריך שלו נבדק בכתבה עצמה (stale_links)

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
assert bot.MODELS == ["gpt-6.1-terra", "gpt-6-luna"]  # gpt-5-mini and gpt-4o-mini are shut down on 2026-12-11 / 2027-01-14
assert bot.plain_hebrew("ת״א 35 ונאסד״ק") == 'ת"א 35 ונאסד"ק'

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
msgs, _ = bot.render(now, [], None, {}, {"israel": [good], "ai": [dict(good, source_title="x")], "world": [dict(good, id="w2", source_title="Iran talks")]})
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
eight = bot.register("v", [dict(own, title=f"story {n}", link=f"https://v/{n}", source=f"src{n}") for n in range(8)])
msgs, _ = bot.render(now, ["🟢 a", "🔴 b"], None, {}, {"world": [dict(good, id=e["id"], source_title=e["title"]) for e in eight]})
assert sum(b.startswith("🔹") for b in msgs[0]) == 5
same = bot.register("u", [dict(own, title=f"same {n}", link=f"https://u/{n}", source="BBC" if n < 4 else f"o{n}") for n in range(7)])
msgs, _ = bot.render(now, [], None, {}, {"world": [dict(good, id=e["id"], source_title=e["title"]) for e in same]})
assert sum(b.startswith("🔹") for b in msgs[0]) == 5 and "\n".join(msgs[0]).count("· BBC") == 2  # עד 2 מאותו מקור כשיש מספיק אחרות
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
import aura_report  # AURA HQ: the call counts for the open station, under the model that answered (the fallback)
aura_report._open.append(("news", "editor"))
tries = [bot.requests.ConnectionError("dropped"), Ok()]
assert bot.ask_ai("s", {}) == {"items": []} and [m["model"] for m in aura_report._take_usage("news", "editor")] == [bot.MODELS[1]]
aura_report._open.clear()
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
blocks = bot.topic_blocks("sport", {"sport": [good, iran], "sport_recap": [{"label": "יורוליג", "text": "מכבי 80, ריאל 70", "ids": ["w1"]}]})
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
assert block == '🏟️ <b>אמש במגרשים</b>\n• <b>יורוליג</b> — הפועל ת&quot;א 90, FC Barcelona 93'
assert bot.recap_block("sport", [], res, {"FC Barcelona": "ברצלונה"}).endswith("הפועל ת&quot;א 90, ברצלונה 93")
assert bot.ISRAELI.search("OFI Crete Hapoel Be'er") and bot.he_club("Hapoel Be'er") == 'הפועל ב"ש'  # השם ב-ESPN
# בספורט — רק שורות עם ישראלים
only_il = bot.recap_block("sport", [{"label": "יורוליג", "text": "ולנסיה 84, מילאנו 73", "ids": ["w1"]},
                                    {"label": "ליגת העל", "text": "מכבי חיפה 2, בית\"ר 1", "ids": ["w1"]}])
assert "ולנסיה" not in only_il and "מכבי חיפה" in only_il
# אותה כתבה לא מופיעה בשני נושאים — נשארת בראשון (ספורט לפני בידור)
msgs, _ = bot.render(now, [], None, {}, {"sport": [good], "ent": [good, iran]})
ent = next(m for m in msgs if any("בידור" in b for b in m[:2]))
assert sum(b.startswith("🔹") for b in ent) == 1 and "שיחות" in "\n".join(ent)
assert bot.recap_block("sport", [], []) == ""
dup = bot.recap_block("sport", [{"label": "יורוליג", "text": "ברצלונה 93, הפועל ת\"א 90", "ids": ["w1"]}], res)
assert dup.count("•") == 1  # השורה של ה-AI על אותו משחק לא מוצגת
assert "🇮🇱" not in bot.article(dict(good, emoji="🇮🇱"))

# ✍️ עורך שני: מתקן ניסוח, מוריד כפילות; נכשל — הטקסט המקורי נשאר
ai = {"ent": [dict(good, id="w1", bottom_line="YNET חשף: א"), dict(good, id="w2", title="כפול")],
      "ent_recap": [{"label": "האח הגדול", "text": "x", "ids": ["w1"]}]}
real_ask, bot.ask_ai = bot.ask_ai, lambda s, p: {"topics": [{"key": "ent", "items": [
    {"id": "w1", "title": "א", "bottom_line": "א נקי"}, {"id": "w2", "drop": True}], "recap": [{"n": 0, "text": "y"}]}]}
bot.edit_pass(ai)
assert ai["ent"][0]["bottom_line"] == "א נקי" and ai["ent_recap"][0]["text"] == "y"
assert ai["ent"][-1]["title"] == "כפול"  # מתחת ל-5 — הפריט שהעורך הוריד חוזר לסוף התור (כפילות אמיתית נסננת ב-topic_blocks)
assert sum(b.startswith("🔹") for b in bot.topic_blocks("ent", ai)) == 1
def boom(s, p):
    raise RuntimeError("down")
bot.ask_ai = boom
bot.edit_pass(ai)
assert ai["ent"][0]["bottom_line"] == "א נקי" and bot.FAILURES[-1].startswith("• <b>עורך")
bot.ask_ai = real_ask

# ⚽ ידיעה ספורטיבית בבידור עוברת לספורט; אימוג'י דגל שנמחק לא משאיר רווח
ai = {"sport": [good], "ent": [dict(good, title="האח הגדול לנבחרת ישראל בכדורגל"), iran]}
bot.move_sporty(ai)
assert [e["title"] for e in ai["ent"]] == ["שיחות"] and ai["sport"][-1]["title"].startswith("האח הגדול")
assert "<b>א</b>" in bot.article(dict(good, emoji="🇵🇹"))

# 📺 שורת בלוק על כתבה שכבר הוצגה בספורט, או ספורטיבית — לא בבלוק הבידור; כתבה מתויגת בשם התוכנית
msgs, _ = bot.render(now, [], None, {}, {"sport": [good], "ent": [iran], "ent_recap": [
    {"label": "האח הגדול", "text": "גרסה לנבחרת ישראל", "ids": ["w2"]}, {"label": "הזמר במסכה", "text": "הודח", "ids": ["w1"]}]})
ent = "\n".join(next(m for m in msgs if any("בידור" in b for b in m[:2])))
assert "נבחרת" not in ent and "הזמר במסכה" not in ent  # ספורטיבי / כבר הוצג בספורט
tagged = bot.register("t", [dict(own, title="שחר חסון מול אופירה", show="הזמר במסכה")], now)
assert tagged[0]["found_by_search"] == "הזמר במסכה"

# 📺 לוח שידורים: פריים טיים נשמר היום ונקרא מחר כ"אמש"; שורה מהלוח בלי כתבה — רק אם התוכנית באמת בלוח
import json as _json, os as _os, tempfile
sched = {"items": [{"starts": "2026-11-06T19:16:00Z", "title": "הישרדות - פרק הדחה!", "description": "מועצת שבט"},
                   {"starts": "2026-11-06T10:25:00Z", "title": "בוקר", "description": ""}]}
real_fetch, bot.fetch = bot.fetch, lambda url: _json.dumps(sched).encode()
tv = bot.get_schedule(now.date())
bot.fetch = real_fetch
assert len(tv) == 3 and tv[0]["time"] == "21:16" and tv[0]["title"].startswith("הישרדות")  # 3 ערוצים, רק ערב
real_file, bot.SCHEDULE_FILE = bot.SCHEDULE_FILE, _os.path.join(tempfile.mkdtemp(), "s.json")
bot.save_tv(now.date(), tv)
assert bot.tv_last_night(now.date() + bot.timedelta(days=1)) == tv and bot.tv_last_night(now.date()) == []
bot.SCHEDULE_FILE = real_file
rows = [{"label": "הישרדות", "text": "שי חי הודח", "ids": ["w1"]}, {"label": "האח הגדול", "text": "המצאה", "ids": []}]
shown_rows = bot.recap_rows("ent", rows, tv_last=["הישרדות - פרק הדחה!"])
assert [r["label"] for r, _ in shown_rows] == ["הישרדות"]
# בלי כפל: ידיעה על תוכנית שכבר בבלוק — לא מוצגת
surv = dict(good, id="w2", source_title="Iran talks", title="כוכב הישרדות מתראיין")
blocks = bot.topic_blocks("ent", {"ent": [surv, iran], "ent_recap": rows, "ent_tv_last": ["הישרדות - פרק הדחה!"]})
assert "שי חי הודח" in blocks[0] and len(blocks) == 2 and "הישרדות" not in blocks[1]

# בידור: כתבות מחיפושי הריאליטי — לבלוק בלבד; השאר — לידיעות
gen, rea = bot.split_reality([{"id": "e1"}, {"id": "e2", "found_by_search": "הישרדות"}])
assert [e["id"] for e in gen] == ["e1"] and [e["id"] for e in rea] == ["e2"]
# 📺 הבלוק = הריאליטי ששודר אמש (בקוד): תוכנית שלא שודרה לא נכנסת, ששודרה בלי שורה — מהלוח; "הערב" — רק פתיחת עונה
last = [{"title": "הזמר במסכה - הארנב נתפס ונחשף!", "channel": "קשת 12", "time": "21:15"},
        {"title": "הישרדות - פרק הדחה משוגע!", "channel": "רשת 13", "time": "21:15"}, {"title": "חדשות", "channel": "x", "time": "20:00"}]
tonight = [{"title": "הארץ המובטחת - פרק 1", "channel": "רשת 13", "time": "21:15"},
           {"title": "הכוכב הבא - פרק 1", "channel": "קשת 12", "time": "21:00"}]
rows = [{"label": "הישרדות", "text": "אבי שושן הודח. הכתבה מציינת שהיו תגובות.", "ids": ["w1"]},
        {"label": "רוקדים עם כוכבים", "text": "כתבות עוסקות בזכרונות", "ids": ["w1"]},
        {"label": "הערב", "text": "הארץ המובטחת — פרק 1 (בכורה/פרק ראשון)", "ids": []}]
block = bot.recap_block("ent", rows, tv_last=last, tv_tonight=tonight)
assert "• <b>הישרדות</b> — אבי שושן הודח ·" in block  # משפט על "הכתבה" נמחק
assert "רוקדים" not in block and "הארץ המובטחת" not in block  # לא שודר אמש / לא ריאליטי
assert "• <b>הזמר במסכה</b> — הארנב נתפס ונחשף" in block  # שודר, אין שורה — מהלוח
assert "• <b>הערב</b> — הכוכב הבא, עונה חדשה · קשת 12, 21:00" in block
# כתיבה נקייה: בלי משפטים על הכתבה, ובלי משפט ראשון שחוזר על הכותרת
assert bot.clean_text("ריצ'רד לויד, גיטריסט טלוויז'ן, מת בגיל 75. הוא נאבק במחלה.", "ריצ'רד לויד, גיטריסט טלוויז'ן, מת בגיל 75") == "הוא נאבק במחלה."
assert bot.clean_text("הבמאי מת. פרטים נוספים לא נמסרו בדיווח.") == "הבמאי מת."
# משפט שרק דומה לכותרת (ולא זהה) נשאר — הוא נושא את העובדה
liberman = "ליברמן אמר שאינו מנסה להכשיל והבהיר את עמדותיו לגבי פשרות בחוק הגיוס. דבריו משפיעים על המו\"מ."
assert bot.clean_text(liberman, "ליברמן מבהיר: לא מנסה להכשיל — על פשרות בגיוס").startswith("ליברמן אמר")
assert bot.clean_text("ההצגה בוטלה. המשמעות המיידית: התפקיד נדחה.") == "ההצגה בוטלה. התפקיד נדחה."
assert bot.clean_text("טסלה מחזירה פיקדונות. המשמעות — כמות ההזמנות גבוהה.") == "טסלה מחזירה פיקדונות. כמות ההזמנות גבוהה."
assert bot.clean_text("הכתבה מציינת ש-X.") == "הכתבה מציינת ש-X."  # הכל מטא — עדיף מאשר ריק
# Google News 503 לרגע — מנסים שוב במקום לוותר על המקור
class G:
    def __init__(self, code):
        self.status_code, self.content = code, b"ok"
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)
answers = [G(503), G(200)]
real_get, real_sleep = bot.requests.get, bot.time.sleep
bot.requests.get, bot.time.sleep = (lambda *a, **k: answers.pop(0)), (lambda s: None)
assert bot.fetch("https://news.google.com/x") == b"ok" and not answers
bot.requests.get, bot.time.sleep = real_get, real_sleep
# 📺 שורה בבלוק הריאליטי — רק העובדה
assert bot.short_fact("הישרדות", "הישרדות: אבי שושן הודח; הוא הפסיד מעל מיליון שקל.") == "אבי שושן הודח"
assert bot.short_fact("הזמר במסכה", "הזמר במסכה: הארנב נתפס ונחשף כפי שנרשם בלוח השידורים.") == "הארנב נתפס ונחשף"
assert bot.short_fact("הזמר במסכה", "הארנב נחשף: זו נועה קירל") == "הארנב נחשף: זו נועה קירל"
assert bot.short_fact("הישרדות", "אבי שושן הודח. הוא אמר שזה כואב.") == "אבי שושן הודח"
# 📺 כל ריאליטי: זיהוי מהלוח ע"י AI (רק שמות שבאמת בלוח, + הרשימה הידועה); הבלוק שומר לעצמו את הכתבות שלו
real_ask = bot.ask_ai
bot.ask_ai = lambda s, p: {"reality": ["מירוץ הכוכבים - פרק 3", "תוכנית שלא בלוח", "חדשות"]}
names = bot.reality_names([{"title": "מירוץ הכוכבים - פרק 3", "description": ""}, {"title": "הישרדות - הדחה"}, {"title": "מהדורה"}])
bot.ask_ai = real_ask
assert names == ["מירוץ הכוכבים", "הישרדות"]  # "חדשות" לא בלוח כשם תוכנית
assert bot.reality_on([{"title": "מירוץ הכוכבים - פרק 3"}], names)[0][0] == "מירוץ הכוכבים"
rabbit = dict(good, id="w2", source_title="Iran talks", title="איתי שכטר הוא הזמר במסכה")
msgs, _ = bot.render(now, [], None, {}, {"sport": [rabbit], "ent": [good], "ent_recap": [
    {"label": "הזמר במסכה", "text": "הארנב נחשף: איתי שכטר", "ids": ["w2"]}],
    "ent_tv_last": [{"title": "הזמר במסכה - הארנב נתפס"}], "ent_reality": ["הזמר במסכה"]})
text = "\n".join(sum(msgs, []))
assert "הארנב נחשף: איתי שכטר" in text and "איתי שכטר הוא הזמר במסכה" not in text  # בבלוק, לא כידיעה בספורט
# שדה מה-AI שהגיע כרשימה לא מפיל את הבריף (קרס כך ב-08/11/2026)
assert bot.clean_text(["אבי שושן הודח.", "עוד"]) == "אבי שושן הודח. עוד"
assert bot.recap_block("ent", [{"label": ["הישרדות"], "text": ["אבי שושן הודח"], "ids": ["w1"]}]).count("•") == 1
assert "<b>" in bot.article(dict(good, title=["א"], bottom_line=["ב"]))
# 📈 שוק ההון: נקודה בלי מקף שני; מקורות — כל מקור פעם אחת בשם קצר, עד 3
assert bot.short_source("Globes - Israel Business News") == bot.short_source("גלובס") == "גלובס"
assert bot.short_source("MarketWatch") == "MarketWatch"
ai = {"market_why": [{"label": "תל אביב", "text": "ת\"א-35 זינק 3% — החזק מאז מרץ", "ids": ["w1"]}]}
pub, _ = bot.render(now, ["🟢 a"], None, {}, ai, channel=True)
mkt = "\n".join(next(m for m in pub if any("שוק ההון" in b for b in m[:2])))
assert "• <b>תל אביב</b> — ת&quot;א-35 זינק 3%, החזק מאז מרץ" in mkt
# 🔤 ז'רגון → עברית בכל הבריף; בשוק — נושא אחד בחלק אחד
assert bot.plain_hebrew("CFO של Binance עוזב; לוק-אפ SpaceX; המפגש החזק ביותר; הסשן נסגר") == \
    'סמנכ"ל הכספים של Binance עוזב; תום תקופת החסימה SpaceX; יום המסחר החזק ביותר; יום המסחר נסגר'
assert bot.plain_hebrew("המפגש עם השר") == "המפגש עם השר"  # "מפגש" רגיל לא נוגעים
assert "סמנכ&quot;ל הכספים" in bot.article(dict(good, title="CFO עוזב"))
ai = {"market_why": [{"label": "אינפלציה", "text": "עונת הדיווחים", "ids": []}, {"label": "ת\"א", "text": "זינוק", "ids": []}],
      "watch": [{"label": "נתוני אינפלציה", "text": "בקרוב", "ids": []}]}
pub, _ = bot.render(now, ["🟢 a"], None, {}, ai, channel=True)
mkt = "\n".join(next(m for m in pub if any("שוק ההון" in b for b in m[:2])))
assert "עונת הדיווחים" not in mkt and "בקרוב" in mkt and "זינוק" in mkt
assert bot.short_source("Yahoo Finance") == "Yahoo"
# 🏟️ שורת משחק שסותרת את עצמה (מנצחת עם פחות נקודות) — לא מוצגת; שני משחקים באותו מפעל — שתי שורות
assert bot.contradicts("הפועל ירושלים 59, העמק 65 — הפועל ירושלים חגגה ניצחון שהאריך רצף")
assert not bot.contradicts("הפועל ירושלים 65, העמק 59 — הפועל ירושלים חגגה ניצחון שהאריך רצף")
assert not bot.contradicts("הפועל תל־אביב 1, הפועל באר־שבע 0 — ניצחון דרמטי בדקה ה-91")
two = bot.recap_block("sport", [{"label": "ליגת העל", "text": "מכבי חיפה 2, בני סכנין 0", "ids": ["w1"]},
                                {"label": "ליגת העל", "text": "הפועל ת\"א 1, הפועל ב\"ש 0", "ids": ["w2"]},
                                {"label": "ליגת ווינר", "text": "הפועל ירושלים 59, העמק 65 — הפועל ירושלים חגגה ניצחון", "ids": ["w1"]}])
assert two.count("• <b>ליגת העל</b>") == 2 and "העמק" not in two
# 📺 ריאליטי: רק תוצאה; בלי תוצאה — אין שורה
assert bot.recap_block("ent", [{"label": "הכוורת", "text": "שלושה מתמודדים מתחרים על תואר", "ids": ["w1"]}]) == ""
assert bot.recap_block("ent", [{"label": "הכוורת", "text": "שלושה מתמודדים מתחרים", "ids": []}], tv_last=[{"title": "הכוורת"}], names=["הכוורת"]) == ""
# 📈 בלי דגלים ובלי מקף בתווית
ai = {"market_why": [{"label": "🇨🇳 — אינפלציה במפעלים", "text": "מחירי היצרן טיפסו", "ids": []}]}
pub, _ = bot.render(now, ["🟢 a"], None, {}, ai, channel=True)
mkt = "\n".join(next(m for m in pub if any("שוק ההון" in b for b in m[:2])))
assert "• <b>אינפלציה במפעלים</b> — מחירי היצרן טיפסו" in mkt and "🇨🇳" not in mkt
# ⚽ אותו כוכב — ידיעה אחת; הדוגמה ל-AI בבלוק הספורט — לפי השדות החדשים
avd = bot.register("d", [dict(own, title=t, link=f"https://d/{n}", source=f"s{n}") for n, t in enumerate(
    ["דני אבדיה קלע 30 נקודות", "פורטלנד מאשימה את וומבניאמה אחרי מהלך עם אבדיה", "אבדיה מצביע על הסיבה לקריסת פורטלנד",
     "בארה\"ב מזהים בעיה אצל אבדיה", "חסון וטיאנו אלופי ישראל"])])
msgs, _ = bot.render(now, [], None, {}, {"sport": [dict(good, id=e["id"], source_title=e["title"], title=e["title"]) for e in avd]})
sp = "\n".join(sum(msgs, []))
assert sp.count("אבדיה") == 1 and "חסון וטיאנו" in sp
assert '"text"' in bot.RECAP_FORMAT.format(rule="x", fields=bot.RECAP_FIELDS["sport"])
assert bot.short_source("Bloomberg.com") == "Bloomberg"
# ✏️ מגיה: תיקון לשון מתקבל; שינוי מספר או אורך חריג — נדחה; כשל — הטקסט נשאר
assert bot.safe_fix("פרצת ביינים חושפת 3 בעיות", "פרצת Binance חושפת 3 בעיות") == "פרצת Binance חושפת 3 בעיות"
assert bot.safe_fix("עלה 3%", "עלה 5%") == "עלה 3%" and bot.safe_fix("משפט ארוך מאוד עם הרבה מילים", "קצר") == "משפט ארוך מאוד עם הרבה מילים"
ai = {"world": [dict(good, title="פרצת ביינים", bottom_line="עלה 3%")], "headline": "כותרת",
      "ent_recap": [{"label": "x", "text": "שורה", "ids": []}]}
key, bot.GEMINI_API_KEY = bot.GEMINI_API_KEY, "k"
real_g, bot.ask_gemini = bot.ask_gemini, lambda s, p: {"texts": [t.replace("ביינים", "Binance").replace("3%", "9%") for t in p["texts"]]}
bot.proofread(ai)
assert ai["world"][0]["title"] == "פרצת Binance" and ai["world"][0]["bottom_line"] == "עלה 3%"
bot.ask_gemini = lambda s, p: {"texts": ["רק אחד"]}
bot.proofread(ai)
assert ai["world"][0]["title"] == "פרצת Binance" and bot.FAILURES[-1].startswith("• <b>מגיה")
bot.ask_gemini, bot.GEMINI_API_KEY = real_g, key
# the first Gemini model is gone (404): the next one answers; both gone: an error
class _G:
    def __init__(self, code): self.status_code, self.ok, self.text = code, code == 200, "x"
    def json(self): return {"usageMetadata": {}, "candidates": [{"content": {"parts": [{"text": '{"texts": ["א"]}'}]}}]}
_calls = []
real_post, bot.requests.post = bot.requests.post, lambda url, **k: (_calls.append(url), _G(404 if "model-a" in url else 200))[1]
real_models, bot.GEMINI_MODELS = bot.GEMINI_MODELS, ["model-a", "model-b"]
assert bot.ask_gemini("s", {"texts": ["x"]}) == {"texts": ["א"]} and "model-b" in _calls[-1] and len(_calls) == 2
bot.requests.post = lambda url, **k: _G(404)
try:
    bot.ask_gemini("s", {"texts": ["x"]})
    raise SystemExit("expected an error when every model fails")
except RuntimeError as ex:
    assert "model-b 404" in str(ex)
bot.requests.post, bot.GEMINI_MODELS = real_post, real_models
# 📺 "מי הודח" רק מכתבה; "אירוע הגמר" מהלוח — לא תוצאה
tvl = [{"title": "הישרדות - פרק הדחה משוגע!"}, {"title": "דאבל על הכסף - אירוע הגמר"}]
blk = bot.recap_block("ent", [{"label": "הישרדות", "text": "אבי שושן הודח", "ids": []}], tv_last=tvl, names=["הישרדות", "דאבל על הכסף"])
assert blk == ""
assert "אבי שושן הודח" in bot.recap_block("ent", [{"label": "הישרדות", "text": "אבי שושן הודח", "ids": ["w1"]}], tv_last=tvl, names=["הישרדות"])
# 📈 נבידיה ב"לשים לב" — לא חוזרת ב"מה הזיז" גם בניסוח אחר; ⚽ אבדיה בלי מספר — לא נכנס
ai = {"market_why": [{"label": "משבר ניהולי בנבידיה", "text": "דיווחים על ישיבה", "ids": []}, {"label": "נפט", "text": "עלה", "ids": []}],
      "watch": [{"label": "ישיבת דירקטוריון נבידיה", "text": "בקרוב", "ids": []}]}
pub, _ = bot.render(now, ["🟢 a"], None, {}, ai, channel=True)
mkt = "\n".join(next(m for m in pub if any("שוק ההון" in b for b in m[:2])))
assert "דיווחים על ישיבה" not in mkt and "נפט" in mkt and "בקרוב" in mkt
blocks = bot.topic_blocks("sport", {"sport": [dict(good, title="דני אבדיה: רצף מרשים", bottom_line="מציג רצף"), dict(iran, title="אבדיה קלע 25 נקודות")]})
assert len(blocks) == 2 and "25" in blocks[1]
# 📺 ריאליטי: העובדה בכותרת הכתבה, כתבה מאחרי השידור, ולא משהו שכבר דווח
import tempfile as _tf
real_rep, bot.REPORTED_FILE = bot.REPORTED_FILE, _os.path.join(_tf.mkdtemp(), "r.json")
bot.fact_in_title, bot.after_airing = _real_fit, _real_air
assert bot.fact_in_title("אבי שושן הודח", "אבי שושן הודח מהישרדות בדרמה") and not bot.fact_in_title("אבי שושן הודח", "לאחר ההדחה: אבי שושן שולח מסר")
arts = bot.register("k", [dict(own, title="דנה לוי הודחה מהישרדות", link="https://k/1"), dict(own, title="לאחר ההדחה: אבי שושן שולח מסר", link="https://k/2")])
tvk = [{"title": "הישרדות - פרק הדחה"}]
rows_k = [{"label": "הישרדות", "text": "אבי שושן הודח", "ids": ["k2"]}, {"label": "הישרדות", "text": "דנה לוי הודחה", "ids": ["k1"]}]
got = bot.recap_rows("ent", rows_k, tv_last=tvk, names=["הישרדות"])
assert [r["text"] for r, _ in got] == ["דנה לוי הודחה"]
bot.remember(got, now.date())
assert bot.already_reported("הישרדות", "דנה לוי הודחה") and bot.recap_rows("ent", rows_k, tv_last=tvk, names=["הישרדות"]) == []
late = dict(own, published=bot.datetime.now(bot.IL_TZ) - bot.timedelta(days=3))
assert not bot.after_airing(late, "הישרדות", [{"title": "הישרדות", "time": "21:15"}]) and bot.after_airing(late, "הישרדות", tvk)
bot.REPORTED_FILE = real_rep
# 🔤 שם אחיד; ידיעה שה-AI לא בטוח בה — לא מוצגת
assert bot.plain_hebrew("מנכ\"ל אנבידיה, משבר בנבידיה") == 'מנכ"ל Nvidia, משבר ב-Nvidia'
assert bot.article(dict(good, bottom_line="ראש הממשלה ובני גנץ/איזנקוט (לפי הכותרת) יערכו פגישה")) == ""
# 5️⃣ תמיד 5: כשחסר — משלימים ממה שנדחה רק בגלל "אותו מקור"; כתבה כפולה עדיין לא חוזרת
six = bot.register("f", [dict(own, title=f"fill {n}", link=f"https://f/{n}", source="BBC" if n < 4 else f"s{n}") for n in range(6)])
blocks = bot.topic_blocks("world", {"world": [dict(good, id=e["id"], source_title=e["title"], title=e["title"]) for e in six] * 2})
assert sum(b.startswith("🔹") for b in blocks) == 5 and "fill 5" in "\n".join(blocks)
# ה-AI הוסיף את שם המקור לפני הכותרת — עדיין מזהים את הכתבה
assert bot.resolve(dict(good, source_title="Reuters: Tesla falls 5%"))["link"] == "https://x/1"
# 🏢 משרד הבוטים: בלי מפתח — לא שולח כלום ולא נופל; עם מפתח ו-Supabase שנופל — ממשיך
posts = []
real_post = bot.requests.post
bot.requests.post = lambda *a, **k: posts.append(k["json"])
bot.OFFICE_KEY = ""
bot.office("start", "x")
assert posts == []
bot.OFFICE_KEY = "k"
bot.office("done", "נשלח")
assert posts[-1]["bot"] == "news" and posts[-1]["kind"] == "done"
def down(*a, **k):
    raise bot.requests.ConnectionError("down")
bot.requests.post = down
bot.office("done", "x")  # לא זורק
bot.requests.post, bot.OFFICE_KEY = real_post, ""
bot.FAILURES.clear()

# AURA HQ: תחנה מדווחת "עובדת" ואז "סיימה" עם התוצאה; חריגה מדווחת "נכשלה" ועוברת הלאה כמו שהיא
import aura_report as _ar
_sent, _real_station = [], _ar.station
_ar.station = lambda b, sid, status, headline=None, metrics=None, *a, **k: _sent.append((b, sid, status, headline, metrics))
with bot.station("market", "מושך") as _st:
    _st.done("8 מדדים", indices=8)
assert _sent == [("news", "market", "working", "מושך", None), ("news", "market", "done", "8 מדדים", {"indices": 8})], _sent
_sent.clear()
try:
    with bot.station("tv", "קורא"):
        raise ValueError("boom")
except ValueError:
    pass
else:
    raise AssertionError("a station must not swallow the bot's error")
assert [e[2] for e in _sent] == ["working", "error"] and "boom" in _sent[1][3], _sent
_sent.clear()
try:  # שגיאה בתוך הקוד של הבוט: הדיווח אומר איפה (קובץ, שורה, פונקציה)
    with bot.station("market", "מושך"):
        bot.fmt_market("x", "index", "a", 1.0)  # str >= float: TypeError בתוך bot.py
except TypeError:
    pass
_w = _sent[1][4]["where"]
assert _sent[1][2] == "error" and _w["file"] == "bot.py" and _w["func"] == "fmt_market", _sent
_ar.station = _real_station

print("ok")
