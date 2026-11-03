# Morning news bot

Hebrew news/markets brief to the public channel 'בריף בוקר עם דני'; personal stocks and failure report go private only. Triggered by Yossi's Vercel Cron (`/api/news_cron`); the GitHub schedule is a backup. Current model setup is Maor's choice — don't re-propose cheaper ones.

## Working with Maor
- Reply in Hebrew; code, commands and commit messages stay in English. Say exactly what you'll do next and what you need from him.
- He often works from iPhone/iPad in cloud sessions, with the Mac off. End every task with a pushed branch and a PR he can merge from the phone. Never push to main yourself.
- Secrets (.env) are not in the repo. If a task needs one, say which and stop.
- Release flow: push to a `test/...` branch, run the workflow with `--ref` so a real Telegram message arrives, and merge to main only after Maor OKs what he sees in Telegram (layout, RTL, accuracy). Read logs before guessing at a fix.
- Keep AI calls cheap; he watches token cost.
