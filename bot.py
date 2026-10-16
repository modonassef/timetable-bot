"""Send today's timetable to Telegram.

Classes come from your KUSSS calendar link (KUSSS_ICAL_URL) when it's set,
so room changes and cancellations are picked up automatically. If the link
isn't set or KUSSS can't be reached, the saved schedule.json is used instead.

Usage:
  python bot.py              send today's classes
  python bot.py --dry-run    print the message instead of sending
  python bot.py --date 2026-10-19 --dry-run   preview a specific day
  python bot.py --only-hour 7   only send if it's currently 07:xx in the
                                schedule's timezone (handles summer/winter time)
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from functools import partial
from html import escape as html_escape
from pathlib import Path

HERE = Path(__file__).parent
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
escape = partial(html_escape, quote=False)  # Telegram only needs <, > and & escaped
EXAM_NOTE = "several halls listed, probably an exam: check KUSSS for yours"


def load_env_file():
    """Load TELEGRAM_* / KUSSS_* values from a local .env file (for running on your PC)."""
    env = HERE / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def get_tz(tz_name):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(tz_name)
    except Exception:
        return None  # fall back to the machine's local time


def today_in(tz_name):
    return datetime.now(get_tz(tz_name))


def parse_ical_time(params, value, tz):
    """Turn an iCal DTSTART/DTEND value into a datetime in the schedule's timezone."""
    if "T" not in value:  # all-day event
        return datetime.strptime(value[:8], "%Y%m%d")
    moment = datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    if value.endswith("Z"):
        return moment.replace(tzinfo=timezone.utc).astimezone(tz)
    return moment  # already local time (TZID=Europe/Vienna)


def unescape_ical(text):
    return (text.replace("\\n", " ").replace("\\N", " ")
                .replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\").strip())


COURSE_TYPES = {
    "VL": "Lecture", "VO": "Lecture", "UE": "Exercise", "KV": "Lecture + Exercise",
    "KS": "Course", "KO": "Tutorial", "SE": "Seminar", "PS": "Proseminar",
    "PR": "Lab", "VK": "Intensive course", "IK": "Interactive course",
}


def tidy_summary(summary):
    """'VL Hands-on AI I / Rainer Dangl / (365211/2026W)' -> ('Hands-on AI I', 'Lecture, Dangl')
    'Course-Exam / VL Hands-on AI II / Rainer Dangl / (...)' -> ('📝 Exam: Hands-on AI II', 'Dangl')"""
    summary = re.sub(r"\s+", " ", summary)
    parts = [p.strip() for p in summary.split(" / ")]
    if parts and re.fullmatch(r"\(.*\)?", parts[-1]):  # drop "(365211/2026W)"
        parts.pop()
    is_exam = bool(parts) and parts[0] == "Course-Exam"
    if is_exam:
        parts.pop(0)
    if not parts:
        return summary, ""
    kind, _, title = parts[0].partition(" ")
    if kind not in COURSE_TYPES:
        kind, title = "", parts[0]
    title = title.replace(" - Level according to CEFR", "")
    lecturers = ", ".join(name.split()[-1] for name in " / ".join(parts[1:]).split(",") if name.strip())
    if is_exam:
        return f"📝 Exam: {title}", lecturers
    detail = ", ".join(x for x in (COURSE_TYPES.get(kind, ""), lecturers) if x)
    return title, detail


def fetch_ical_classes(url, tz_name):
    url = url.strip().replace("webcal://", "https://", 1)
    request = urllib.request.Request(url, headers={"User-Agent": "timetable-bot"})
    text = urllib.request.urlopen(request, timeout=30).read().decode("utf-8", "replace")
    text = re.sub(r"\r?\n[ \t]", "", text)  # undo iCal line folding
    tz = get_tz(tz_name)

    classes = []
    for block in text.split("BEGIN:VEVENT")[1:]:
        props = {}
        for line in block.split("END:VEVENT")[0].splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                name, _, params = key.partition(";")
                props.setdefault(name.upper(), (params, value.strip()))
        if "DTSTART" not in props:
            continue
        start = parse_ical_time(*props["DTSTART"], tz)
        end = parse_ical_time(*props.get("DTEND", props["DTSTART"]), tz)
        subject, detail = tidy_summary(unescape_ical(props.get("SUMMARY", ("", "Class"))[1]))
        room = unescape_ical(props.get("LOCATION", ("", ""))[1]).strip(" -")
        # Session notes like "1. Exam" or "HS 2 moved to HS 1". Exam entries only
        # carry the unregistration deadline there, which isn't useful in the morning.
        info = "" if subject.startswith("📝") else unescape_ical(props.get("DESCRIPTION", ("", ""))[1])
        classes.append({
            "date": start.strftime("%Y-%m-%d"),
            "start": start.strftime("%H:%M"),
            "end": end.strftime("%H:%M"),
            "subject": subject,
            "detail": detail,
            "room": room or "room not listed",
            "info": info[:120],
        })
    return merge_rooms(classes)


def merge_rooms(classes):
    """Combine sessions that only differ by room (exams spread over several halls)."""
    merged = {}
    for c in classes:
        key = (c["date"], c["start"], c["end"], c["subject"], c.get("detail", ""))
        if key in merged:
            if c["room"] not in merged[key]["room"].split(" / "):
                merged[key]["room"] += " / " + c["room"]
                merged[key]["note"] = EXAM_NOTE
        else:
            merged[key] = dict(c)
    classes = list(merged.values())

    # When you're registered for an exam, KUSSS lists it twice: the course session
    # (all halls) and your exam registration (your hall). Show them as one entry.
    exams = {(c["date"], c["start"], c["subject"][len("📝 Exam: "):]): c
             for c in classes if c["subject"].startswith("📝 Exam: ")}
    result = []
    for c in classes:
        exam = exams.get((c["date"], c["start"], c["subject"]))
        if exam:
            exam["info"] = exam["info"] or c.get("info", "")
            exam["all_rooms"] = c["room"]
            continue
        if "exam" in c.get("info", "").lower():
            c.pop("note", None)  # KUSSS already says it's an exam
        result.append(c)
    return result


def build_message(classes, skip_dates, day, warning=None):
    iso = day.strftime("%Y-%m-%d")
    if iso in skip_dates:
        return None
    name = DAYS[day.weekday()]
    todays = sorted((c for c in classes if c["date"] == iso), key=lambda c: c["start"])
    header = f"📚 Good morning! {name.capitalize()}, {day:%d %b}"
    if warning:
        header += f"\n⚠️ {escape(warning)}"
    if not todays:
        return f"{header}\n\nNo classes today 🎉"
    lines = []
    for c in todays:
        line = f"🕘 {c['start']}–{c['end']}  <b>{escape(c['subject'])}</b>"
        if c.get("detail"):
            line += f" ({escape(c['detail'])})"
        if c.get("all_rooms"):
            line += f"\n      📍 Your hall: {escape(c['room'])}"
            line += f"\n      🏛️ All halls: {escape(c['all_rooms'])}"
        else:
            line += f"\n      📍 {escape(c['room'])}"
        if c.get("info"):
            line += f"\n      ℹ️ {escape(c['info'])}"
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
    load_env_file()
    cfg = json.loads((HERE / "schedule.json").read_text(encoding="utf-8"))
    tz_name = cfg.get("timezone", "UTC")
    args = sys.argv[1:]

    if "--date" in args:
        day = datetime.strptime(args[args.index("--date") + 1], "%Y-%m-%d")
    else:
        day = today_in(tz_name)

    if "--only-hour" in args:
        # GitHub runs both a 05:00 and a 06:00 UTC cron. Decide from which cron
        # *triggered* this run (not the clock), since GitHub often starts runs late.
        send_hour = int(args[args.index("--only-hour") + 1])
        offset = int(day.utcoffset().total_seconds() // 3600) if day.utcoffset() else 0
        target_utc_hour = (send_hour - offset) % 24
        cron = os.environ.get("TRIGGER_CRON", "")
        cron_hour = int(cron.split()[1]) if cron else day.astimezone(timezone.utc).hour
        if cron_hour != target_utc_hour:
            print(f"Triggered by the {cron_hour:02d}:00 UTC cron; today's send is the "
                  f"{target_utc_hour:02d}:00 UTC one ({send_hour:02d}:00 local), skipping.")
            return

    if day.weekday() >= 5:
        print("Weekend - nothing to send.")
        return

    classes, warning = cfg["classes"], None
    ical_url = os.environ.get("KUSSS_ICAL_URL", "").strip()
    if ical_url:
        try:
            classes = fetch_ical_classes(ical_url, tz_name)
            print(f"Loaded {len(classes)} sessions from KUSSS.")
        except Exception as e:
            print(f"Couldn't load KUSSS calendar ({type(e).__name__}), using schedule.json.")
            warning = "Couldn't reach KUSSS, showing the saved timetable (may be out of date)"

    message = build_message(classes, cfg.get("skip_dates", []), day, warning)
    if message is None:
        print("Skip date - nothing to send.")
        return

    if "--dry-run" in args:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles can't print emoji otherwise
        print(message)
        return

    # .strip() guards against stray spaces/newlines pasted into GitHub secrets
    send(os.environ["TELEGRAM_BOT_TOKEN"].strip(), os.environ["TELEGRAM_CHAT_ID"].strip(), message)
    print("Sent.")


if __name__ == "__main__":
    main()
