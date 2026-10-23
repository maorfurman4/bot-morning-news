# 📰 בריף חדשות בוקר

בוט טלגרם ששולח כל בוקר סיכום חדשות בעברית.

## מה הוא עושה
1. מושך חדשות מ-24 השעות האחרונות (NewsAPI) ב-4 נושאים: ישראל, בינה מלאכותית, עולם, וחברות במעקב
2. GPT-4o בוחר 3 כתבות חשובות מכל נושא, מתרגם לעברית ומוסיף שורה תחתונה וקישור
3. שולח לטלגרם

חברות במעקב (ברשימה `COMPANIES` בתוך `bot.py`): Mobileye, Intel, Tesla, Amazon, D-Wave, Klarna, Grab, Google, Teva, Supernus, Novo Nordisk, ASPI

## מתי
כל בוקר (GitHub Actions, `.github/workflows/main.yml`). הרצה ידנית: Actions → "Daily Morning Briefing Analyst" → Run workflow.

## קבצים
| קובץ | תפקיד |
|---|---|
| `bot.py` | כל הלוגיקה |
| `requirements.txt` | ספריות פייתון |
| `.github/workflows/main.yml` | התזמון |
| `.github/workflows/keepalive.yml` | שומר שגיטהאב לא יכבה את התזמון |

## סודות (Settings → Secrets → Actions)
`OPENAI_API_KEY`, `NEWS_API_KEY`, `TELEGRAM_TOKEN_NEWS`, `CHAT_ID_NEWS`
