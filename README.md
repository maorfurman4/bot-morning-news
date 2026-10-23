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

בכל נושא 3–6 ידיעות, כל אחת: כותרת מודגשת, "השורה התחתונה" וקישור לכתבה + שם המקור.

## מאיפה המידע
- **מספרים**: Yahoo Finance (yfinance) — מחושבים בקוד, לא ע"י ה-AI
- **חדשות**: RSS קבוע (`FEEDS`: גלובס, ynet, Times of Israel, BBC, CNBC, TechCrunch, MIT Technology Review, IEEE Spectrum) + Google News מסונן למקורות אמינים (`TRUSTED`). רק 26 השעות האחרונות
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
