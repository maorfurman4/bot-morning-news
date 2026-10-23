# 📰 בריף חדשות בוקר

בוט טלגרם ששולח כל בוקר בריף חדשות וכלכלה בעברית.

## מה בהודעה
1. 🔝 3 הדברים החשובים הבוקר
2. 📊 תמונת מצב שוקים — S&P 500, נאסד"ק, דאו, ת"א-35, VIX, אג"ח 10 שנים, דולר/שקל, ברנט + "מה זז באמת"
3. 💼 המניות שלי (`HOLDINGS`) — שינוי יומי; מניה שזזה מעל 3% (`DRAMATIC`) מקבלת הסבר מכתבות
4. 🇮🇱 ישראל · 🌍 עולם · 💰 עסקים · 🤖 טכנולוגיה ו-AI
5. 📖 לקריאה מעמיקה
6. ⚠️ מה לא עבד (רק אם משהו נכשל)

## מאיפה המידע
- **מספרים**: Yahoo Finance (yfinance) — מחושבים בקוד, לא ע"י ה-AI
- **חדשות**: RSS קבוע (`FEEDS`: גלובס, ynet, Times of Israel, BBC, CNBC, TechCrunch) + Google News מסונן למקורות אמינים (`TRUSTED`). רק 26 השעות האחרונות
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
