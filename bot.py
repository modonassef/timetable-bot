"""Send today's timetable to Telegram.

Usage:
  python bot.py              send today's classes
  python bot.py --dry-run    print the message instead of sending
  python bot.py --date 2026-10-19 --dry-run   preview a specific day
  python bot.py --only-hour 7   only send if it's currently 07:xx in the
                                schedule's timezone (handles summer/winter time)
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from html import escape
from pathlib import Path

HERE = Path(__file__).parent
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def load_env_file():
    """Load TELEGRAM_* values from a local .env file (for running on your PC)."""
    env = HERE / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def today_in(tz_name):
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tz_name))
    except Exception:
        return datetime.now()  # fall back to the machine's local time


def build_message(cfg, day):
    iso = day.strftime("%Y-%m-%d")
    if iso in cfg.get("skip_dates", []):
        return None
    name = DAYS[day.weekday()]
    classes = sorted(
        (c for c in cfg["classes"] if c["date"] == iso), key=lambda c: c["start"]
    )
    header = f"📚 Good morning! {name.capitalize()}, {day:%d %b}"
    if not classes:
        return f"{header}\n\nNo classes today 🎉"
    lines = []
    for c in classes:
        line = f"🕘 {c['start']}–{c['end']}  <b>{escape(c['subject'])}</b>\n      📍 {escape(c['room'])}"
        if c.get("note"):
            line += f"\n      ⚠️ {escape(c['note'])}"
        lines.append(line)
    return f"{header}\n\n" + "\n\n".join(lines)


def send(token, chat_id, text):
    data = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    ).encode()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    urllib.request.urlopen(url, data, timeout=30).read()


def main():
    cfg = json.loads((HERE / "schedule.json").read_text(encoding="utf-8"))
    args = sys.argv[1:]

    if "--date" in args:
        day = datetime.strptime(args[args.index("--date") + 1], "%Y-%m-%d")
    else:
        day = today_in(cfg.get("timezone", "UTC"))

    if "--only-hour" in args and day.hour != int(args[args.index("--only-hour") + 1]):
        print(f"It's {day:%H:%M} locally - not the send hour, skipping.")
        return

    if day.weekday() >= 5:
        print("Weekend - nothing to send.")
        return

    message = build_message(cfg, day)
    if message is None:
        print("Skip date - nothing to send.")
        return

    if "--dry-run" in args:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles can't print emoji otherwise
        print(message)
        return

    load_env_file()
    send(os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"], message)
    print("Sent.")


if __name__ == "__main__":
    main()
