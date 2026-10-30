# 📰 בריף חדשות בוקר

בוט טלגרם ששולח כל בוקר בריף חדשות וכלכלה בעברית.

## לאן
- **ערוץ טלגרם** (`NEWS_CHANNEL_ID`, רק הבוט כותב): ישראל, AI, טכנולוגיה, עולם, שוק ההון — בפתיח כללי "בוקר טוב"
- **אליך בפרטי** (`CHAT_ID_NEWS`): 💼 המניות שלך (`HOLDINGS`) והכתבות עליהן, ודוח "מה לא עבד" — לעולם לא לערוץ
- בלי `NEWS_CHANNEL_ID` — הכל נשלח אליך

## מה נשלח — הודעה נפרדת לכל נושא
1. 🇮🇱 ישראל
2. 🤖 בינה מלאכותית (AI)
3. 🦾 טכנולוגיה ורובוטיקה
4. 🌍 אקטואליה עולמית
5. 📈 שוק ההון — כותרת היום, טבלת סגירה (S&P 500, Nasdaq, Dow, TA-35, VIX, US 10Y, USD/ILS, Brent),
   "מה הזיז את השוק" (2), "על מה לשים לב" (2 — ריבית, אינפלציה, דוחות, גאופוליטיקה, נפט),
   🕵️ רכישות פנים (עד 5 קניות של מנכ"לים/סמנכ"לים/דירקטורים מעל 100 אלף דולר מהיממה האחרונה), ידיעה בולטת ושורת מקורות.
   כל סיפור מופיע פעם אחת
6. 💼 המניות שלך (בפרטי) — מניה שזזה מעל 3% (`DRAMATIC`) מקבלת הסבר מכתבות
7. ⚠️ מה לא עבד (בפרטי, רק אם משהו נכשל)

בכל נושא 5 הידיעות הרלוונטיות ביותר (הודעה אחת לנושא), כל אחת: כותרת מודגשת, "השורה התחתונה" וקישור לכתבה + שם המקור.
כל נושא מסוכם בקריאת AI נפרדת (gpt-5-mini, ואם לא זמין — gpt-4o-mini), וכל ידיעה נבדקת מול כותרת הכתבה
שהקישור שלה מוצג; ידיעה שלא מתאימה לכתבה אמיתית לא נשלחת.

## מאיפה המידע
- **מספרים**: Yahoo Finance (yfinance) — מחושבים בקוד, לא ע"י ה-AI
- **רכישות פנים**: OpenInsider (דיווחי Form 4 ל-SEC, חינמי) — נבנה בקוד, לא ע"י ה-AI. GuruFocus חוסם גישה אוטומטית
  ודורש API בתשלום
- **חדשות**: כ-45 מקורות ב-`FEEDS` — ישראל: הכותרות הראשיות של Google News ישראל, ynet, גלובס, הארץ, מעריב, וואלה,
  כאן 11, mako, Times of Israel, Jerusalem Post, Reuters, כלכליסט, TheMarker; AI: TechCrunch, MIT Technology Review,
  Ars Technica, Wired, The Verge, The Decoder, Reuters; טכנולוגיה: BBC, TechCrunch, IEEE Spectrum, Ars Technica, Wired,
  Engadget, The Verge, The Register, Electrek, Geektime, Reuters; עולם: BBC, Reuters, AP, Guardian, New York Times,
  Al Jazeera, NPR, CNBC; שוק: CNBC, MarketWatch, Investing.com, גלובס שוק ההון, Bloomberg, Reuters +
  Google News מסונן למקורות אמינים (`TRUSTED`). רק 26 השעות האחרונות, עד 6 כתבות ממקור ועד 50 לנושא (`PER_TOPIC`),
  לסירוגין בין המקורות
- **סיכום**: ה-AI בוחר ומתרגם רק מתוך הכתבות שקיבל. הקישור והמקור ליד כל פריט מגיעים מהנתונים, לא מה-AI

## מתי
כל בוקר ב-02:30 UTC = 04:30 בחורף / 05:30 בקיץ (GitHub Actions, `.github/workflows/main.yml`). הרצה ידנית: Actions → "Daily Morning Briefing Analyst" → Run workflow.

## קבצים
| קובץ | תפקיד |
|---|---|
| `bot.py` | כל הלוגיקה. `python bot.py --dry-run` מדפיס בלי לשלוח |
| `test_bot.py` | בדיקות קצרות: `python test_bot.py` |
| `requirements.txt` | ספריות פייתון |
| `.github/workflows/main.yml` | התזמון |
| `.github/workflows/keepalive.yml` | שומר שגיטהאב לא יכבה את התזמון |

## סודות (Settings → Secrets → Actions)
`OPENAI_API_KEY`, `TELEGRAM_TOKEN_NEWS`, `CHAT_ID_NEWS`, `NEWS_CHANNEL_ID` (אופציונלי)
