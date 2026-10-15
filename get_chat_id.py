"""Print your Telegram chat ID. Send your bot any message first, then run:
  python get_chat_id.py <BOT_TOKEN>
"""
import json
import sys
import urllib.request

token = sys.argv[1]
with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30) as r:
    updates = json.load(r)["result"]

if not updates:
    print("No messages yet - send your bot a message in Telegram, then run this again.")
for u in updates:
    chat = (u.get("message") or u.get("edited_message") or {}).get("chat")
    if chat:
        print(f"chat_id = {chat['id']}  ({chat.get('first_name') or chat.get('title')})")
