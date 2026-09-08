import json
import urllib.request
import re
from pathlib import Path

ROOT = Path("/home/shogo/DayTrade_Pro")

def load_env(key: str) -> str:
    path = ROOT / "config" / "secrets.env"
    if not path.exists(): return ""
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    return ""

def slack_post(text: str):
    token = load_env("SLACK_BOT_TOKEN")
    channel = load_env("SLACK_CHANNEL_ALERTS")
    if not token or not channel:
        print("Slack Token/Channel is not set. Outputting to standard output only.")
        print(text)
        return
        
    data = json.dumps({"channel": channel, "text": text}, ensure_ascii=False).encode()
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage", data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            res = json.loads(r.read().decode())
            if not res.get("ok"): print(f"Slack Error: {res}")
    except Exception as e:
        print(f"Slack HTTP Error: {e}")

TARGETS_FILE = ROOT / "data" / "today_targets.json"
data = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
targets = data.get("targets", [])

lines = [
    "【買い付け枠】確定版 (日経寄与度上位への差し替え完了)\n",
]

for i, t in enumerate(targets, 1):
    px = t["entry_price"]
    shares = t["shares"]
    target_px = t.get("target", px * 1.015)
    stop_px = t.get("stop", px * 0.98)
    status_str = " (利確済み)" if t["status"] == "HIT_TP" else ""
    
    lines.append(f"{i}. {t['code']} {t['name']}\n   現在値: {px:,.1f}円\n   数量: {shares:,}株 (約 {px * shares / 10000:,.0f}万円)\n   状態: {t['status']}{status_str}\n")

text = "\n".join(lines)
slack_post(text)
print("Notified Slack.")
