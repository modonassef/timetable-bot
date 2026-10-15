# Timetable Bot

Sends you a Telegram message every weekday morning with that day's classes, times, and lecture halls.

## 1. Create the bot
1. In Telegram, open **@BotFather** and send `/newbot`. Follow the prompts and copy the **token** it gives you.
2. Open your new bot and send it any message (e.g. "hi").
3. Run `python get_chat_id.py <TOKEN>` and copy the `chat_id`.

## 2. Fill in your timetable
`schedule.json` lists every class session by date (taken from the KUSSS timetable PDF). Each entry has `date`, `start`, `end`, `subject`, `room`, and an optional `note`. Add or remove entries if your timetable changes, and list any days to skip in `skip_dates`.

Preview a day: `python bot.py --date 2026-10-19 --dry-run`

## 3. Run it automatically

### Option A: GitHub Actions (free; your PC can be off)
1. Push this folder to a **private** GitHub repo.
2. Go to repo → Settings → Secrets and variables → Actions, and add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
3. Edit the cron time in `.github/workflows/daily.yml` (it's in UTC).
4. Test it: Actions tab → "Daily timetable" → Run workflow.

Note: GitHub's scheduled runs can arrive 5–15 minutes late.

### Option B: Your Windows PC (it must be on at that time)
1. Create a `.env` file next to `bot.py`:
   ```
   TELEGRAM_BOT_TOKEN=123456:ABC...
   TELEGRAM_CHAT_ID=123456789
   ```
2. Register a weekday task at 07:00:
   ```
   schtasks /Create /TN "TimetableBot" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 07:00 /TR "python C:\Users\modon_y971jgn\projects\timetable-bot\bot.py"
   ```
