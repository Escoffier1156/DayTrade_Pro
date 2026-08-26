#!/usr/bin/env python3
"""
大引け後（15:00以降）に実行する日次レポートスクリプト。
data/today_targets.json を読み込み、
本日の運用結果（利確・損切・未決済）を集計してSlackに通知する。
"""
import datetime as _dt
import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SECRETS_FILE = ROOT / "config" / "secrets.env"
TARGETS_FILE = DATA_DIR / "today_targets.json"

def load_env(name: str) -> str:
    v = os.environ.get(name)
    if v:
        return v
    if SECRETS_FILE.exists():
        for line in SECRETS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{name}=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip()
    return ""

def slack_post(text: str):
    token = load_env("SLACK_BOT_TOKEN")
    channel = load_env("SLACK_CHANNEL_ALERTS")
    if not token or not channel:
        print("Slack Token/Channel未設定。標準出力のみ。")
        print(text)
        return
        
    data = json.dumps({"channel": channel, "text": text}, ensure_ascii=False).encode()
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage", data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            pass
    except Exception as e:
        print(f"Slack送信失敗: {e}")

def main():
    if not TARGETS_FILE.exists():
        print("本日のターゲットファイルが存在しません。")
        return
        
    try:
        data = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ターゲットファイルの読み込み失敗: {e}")
        return
        
    today_str = _dt.date.today().isoformat()
    target_date = data.get("date")
    
    targets = data.get("targets", [])
    
    total_pnl = 0
    lines = [
        f"【本日の運用結果レポート】 ({target_date})",
        "---"
    ]
    
    if not targets:
        lines.append("本日の取引対象銘柄はありませんでした。")
    else:
        for i, t in enumerate(targets, 1):
            code = t["code"]
            name = t["name"]
            status = t["status"]
            entry = t["entry_price"]
            shares = t["shares"]
            latest = t.get("latest_price", entry)
            exit_px = latest
            
            if status == "HIT_TP":
                result = "🟢 利確"
            elif status == "HIT_SL":
                result = "🔴 損切"
            else:
                result = "⚪ 未決済（大引）"
                
            pnl = (exit_px - entry) * shares
            total_pnl += pnl
            
            lines.append(f"{i}. {code} {name} - {result}")
            lines.append(f"   買値: {entry:,.1f}円 -> 決済値: {exit_px:,.1f}円")
            lines.append(f"   数量: {shares:,}株")
            lines.append(f"   損益: {pnl:+,.0f}円")
            lines.append("")
            
        lines.append("---")
        lines.append(f"💰 本日の合計損益: {total_pnl:+,.0f}円")
        
    text = "\n".join(lines)
    
    print(text)
    
    if target_date == today_str:
        slack_post(text)
    else:
        print("※ 日付が今日ではないためSlack通知は行いませんでした。")

if __name__ == "__main__":
    main()
