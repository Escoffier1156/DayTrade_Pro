#!/usr/bin/env python3
"""
ザラ場中（9:00〜15:00）に毎分実行されるモニタリングスクリプト。
data/today_targets.json を読み込み、OPENの銘柄に対して
株探の個別ページから現在値をスクレイピングし、
利確（TP）または損切（SL）に達していればSlackに通知する。
"""
import datetime as _dt
import gzip
import json
import os
import re
import time
import urllib.request
from pathlib import Path

STOCK_URL = "https://kabutan.jp/stock/?code={code}"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SECRETS_FILE = ROOT / "config" / "secrets.env"
TARGETS_FILE = DATA_DIR / "today_targets.json"
HISTORY_FILE = DATA_DIR / "trade_history.json"

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

def fetch_bulk_prices(targets: list, cookie: str) -> dict:
    codes = [t["code"] for t in targets if t["status"] == "OPEN"]
    if not codes:
        return {}
        
    url = "https://kabutan.jp/favorite/stock/"
    query = []
    for c in codes:
        query.append(("codes[]", c))
    
    data = urllib.parse.urlencode(query).encode("utf-8")
    
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": UA, 
            "Cookie": cookie, 
            "Accept-Encoding": "gzip", 
            "Content-Type": "application/x-www-form-urlencoded"
        }
    )
    
    prices = {}
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            res_text = raw.decode("utf-8", "replace")
            res_json = json.loads(res_text)
            
            # API returns a list of lists: [[code, price, ...], ...]
            rows = res_json if isinstance(res_json, list) else res_json.get("data", [])
            for row in rows:
                if len(row) >= 2:
                    code = str(row[0])
                    px_str = str(row[1]).replace(",", "")
                    if px_str and px_str not in ["－", "-"]:
                        try:
                            prices[code] = float(px_str)
                        except ValueError:
                            pass
    except Exception as e:
        print(f"API Bulk Fetch Error: {e}")
        
    return prices

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
        print(f"Slack post error: {e}")

def record_trade(code: str, name: str, side: str, qty: int, price: float, pnl: float):
    # side: "SELL(TP)" or "SELL(SL)"
    now_str = _dt.datetime.now().strftime("%H:%M:%S")
    trade = {
        "time": now_str,
        "ticker": code,
        "name": name,
        "side": side,
        "qty": qty,
        "price": price,
        "pnl": pnl
    }
    history = []
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except json.JSONDecodeError:
            pass
    history.append(trade)
    # 常に最新が一番上に来るように新しいものを配列の最後に入れる（フロントでリバースする）
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def monitor_step(iteration_count: int):
    if not TARGETS_FILE.exists():
        print("本日のターゲットファイルが存在しません。")
        return False
        
    try:
        data = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ターゲットファイルの読み込み失敗: {e}")
        return False
        
    # 日付チェック（今日のものでなければスキップ）
    today_str = _dt.date.today().isoformat()
    if data.get("date") != today_str:
        print(f"ターゲットファイルが古い（{data.get('date')}）ためスキップします。")
        return False
        
    cookie = load_env("KABUTAN_COOKIE")
    targets = data.get("targets", [])
    updated = False
    
    try:
        # 1発で全銘柄の価格を取得
        prices = fetch_bulk_prices(targets, cookie)
        
        for t in targets:
            if t["status"] != "OPEN":
                continue
                
            code = t["code"]
            px = prices.get(code)
            
            if px is None:
                print(f"{code} 価格取得失敗または市場閉鎖")
                continue
                
            t["latest_price"] = px
            
            # 詳細データは取得できないため、一時的にnullまたは既存を維持
            t["volume"] = None
            t["turnover"] = None
            t["vwap"] = None
            t["trades"] = None
            
            is_history_poll = (iteration_count % 4 == 0) # Every 60s
            if is_history_poll:
                if "history" not in t:
                    t["history"] = []
                import time
                current_ts = int(time.time())
                if t["history"] and t["history"][-1]["time"] >= current_ts:
                    current_ts = t["history"][-1]["time"] + 1
                t["history"].append({"time": current_ts, "value": px})
            
            updated = True
            
            entry_px = t["entry_price"]
            target_px = t["target"]
            stop_px = t["stop"]
            
            # 判定
            if px >= target_px:
                t["status"] = "HIT_TP"
                pnl = (px - entry_px) * t["shares"]
                record_trade(code, t['name'], "SELL(TP)", t["shares"], px, pnl)
                msg = (
                    f"【利確到達 :tada:】 {code} {t['name']}\n"
                    f"現在値 {px:,.1f}円 が利確目標 ({target_px:,.1f}円) に到達しました。\n"
                    f"想定利益: +{pnl:,.0f}円"
                )
                slack_post(msg)
                print(f"{code} HIT TP! {px}")
                
            elif px <= stop_px:
                t["status"] = "HIT_SL"
                pnl = (px - entry_px) * t["shares"]
                record_trade(code, t['name'], "SELL(SL)", t["shares"], px, pnl)
                msg = (
                    f"【損切到達 :warning:】 {code} {t['name']}\n"
                    f"現在値 {px:,.1f}円 が損切ライン ({stop_px:,.1f}円) に到達しました。\n"
                    f"想定損失: {pnl:,.0f}円"
                )
                slack_post(msg)
                print(f"{code} HIT SL! {px}")
            else:
                if is_history_poll:
                    print(f"{code} {px:,.1f}円 (TP: {target_px:,.1f}, SL: {stop_px:,.1f}) - 維持")
    
        if updated:
            with open(TARGETS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        
        return True
        
    except Exception as e:
        print(f"Monitor step error: {e}")
        return False

# For standalone execution testing
if __name__ == "__main__":
    monitor_step(0)
