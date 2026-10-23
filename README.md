# 📰 בריף חדשות בוקר

בוט טלגרם ששולח כל בוקר בריף חדשות וכלכלה בעברית.

## מה נשלח — הודעה נפרדת לכל נושא
1. 🇮🇱 ישראל
2. 🤖 בינה מלאכותית (AI)
3. 🦾 טכנולוגיה ורובוטיקה
4. 🌍 אקטואליה עולמית
5. 📈 שוק ההון ותיק המניות — S&P 500, נאסד"ק, דאו, ת"א-35, VIX, אג"ח 10 שנים, דולר/שקל, ברנט, "מה זז באמת",
   המניות שלי (`HOLDINGS`); מניה שזזה מעל 3% (`DRAMATIC`) מקבלת הסבר מכתבות
6. ⚠️ מה לא עבד (רק אם משהו נכשל)

בכל נושא 5–8 ידיעות, כל אחת: כותרת מודגשת, "השורה התחתונה" וקישור לכתבה + שם המקור.
כל נושא מסוכם בקריאת AI נפרדת (gpt-5, ואם לא זמין — gpt-4o), וכל ידיעה נבדקת מול כותרת הכתבה
שהקישור שלה מוצג; ידיעה שלא מתאימה לכתבה אמיתית לא נשלחת.

## מאיפה המידע
- **מספרים**: Yahoo Finance (yfinance) — מחושבים בקוד, לא ע"י ה-AI
- **חדשות**: כ-30 מקורות ב-`FEEDS` — ישראל: הכותרות הראשיות של Google News ישראל (ynet, mako, מעריב, כאן, גלובס...), ynet, גלובס, הארץ, Times of Israel, Reuters, כלכליסט, TheMarker; AI: TechCrunch, MIT Technology Review, Ars Technica, Wired, The Verge; טכנולוגיה: BBC, TechCrunch, IEEE Spectrum, Ars Technica, Wired, Engadget, The Verge; עולם: BBC, Reuters, Guardian, Al Jazeera, NPR, CNBC; שוק: CNBC, MarketWatch + Google News מסונן למקורות אמינים (`TRUSTED`). רק 26 השעות האחרונות
- **סיכום**: GPT-4o בוחר ומתרגם רק מתוך הכתבות שקיבל. הקישור והמקור ליד כל פריט מגיעים מהנתונים, לא מה-AI

## מתי
כל בוקר ב-02:30 UTC (GitHub Actions, `.github/workflows/main.yml`). הרצה ידנית: Actions → "Daily Morning Briefing Analyst" → Run workflow.

## קבצים
| קובץ | תפקיד |
|---|---|
| `bot.py` | כל הלוגיקה. `python bot.py --dry-run` מדפיס בלי לשלוח |
| `test_bot.py` | בדיקות קצרות: `python test_bot.py` |
| `requirements.txt` | ספריות פייתון |
| `.github/workflows/main.yml` | התזמון |
| `.github/workflows/keepalive.yml` | שומר שגיטהאב לא יכבה את התזמון |

## סודות (Settings → Secrets → Actions)
`OPENAI_API_KEY`, `TELEGRAM_TOKEN_NEWS`, `CHAT_ID_NEWS`
