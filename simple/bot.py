#!/usr/bin/env python3
"""
Integrated Master Bot (bot.py)
A daemon script that autonomously executes everything based on the time,
from fetching J-Quants data to screening, intraday monitoring, and post-close reporting.
"""
import datetime as _dt
import gzip
import html as _html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# --- Constants and Paths ---
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SECRETS_FILE = ROOT / "config" / "secrets.env"
UNIVERSE_FILE = DATA_DIR / "universe_latest.json"
TARGETS_FILE = DATA_DIR / "today_targets.json"
HISTORY_FILE = DATA_DIR / "trade_history.json"
STATE_FILE = DATA_DIR / "bot_state.json"

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

# J-Quants
API_BASE = "https://api.jquants.com/v2"
BARS_DAILY = "/equities/bars/daily"
CALENDAR = "/markets/calendar"
MASTER = "/equities/master"
AVG_WINDOW = 20

# Kabutan Screener
TARGET_URL = "https://kabutan.jp/warning/?mode=2_9&page={page}"
MAX_PAGES = 5
MIN_AVG_VOLUME = 400_000
MIN_AVG_TURNOVER = 3_000_000_000
TP_PCT = 2.5
SL_PCT = 2.0
NIKKEI_STRONG = 0.5
NIKKEI_WEAK = -0.5
TOTAL_CAPITAL = 10_000_000
LOT = 100

_TABLE = re.compile(r'<table class="stock_table[^"]*">(.*?)</table>', re.S)
_TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL = re.compile(r"<t[hd][^>]*>(.*?)</t[hd]>", re.S)

# --- Common Utilities ---
def get_last_run(job_name: str) -> str:
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return state.get(job_name)
        except: pass
    return None

def set_last_run(job_name: str, date_str: str):
    state = {}
    if STATE_FILE.exists():
        try: state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except: pass
    state[job_name] = date_str
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
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
        print("Slack Token/Channel is not set. Outputting to standard output only.")
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

# =========================================================
# fetch_yesterday (Generate J-Quants Universe)
# =========================================================
def api_get(path: str, params: dict, key: str) -> list[dict]:
    rows = []
    page = None
    while True:
        q = dict(params)
        if page:
            q["pagination_key"] = page
        url = f"{API_BASE}{path}?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(url, headers={"x-api-key": key})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                doc = json.loads(r.read())
        except Exception as exc:
            raise RuntimeError(f"{path} Fetch failed: {exc}") from exc
        rows.extend(doc.get("data") or [])
        page = doc.get("pagination_key")
        time.sleep(0.3)
        if not page:
            return rows

def trading_days(key: str, end: _dt.date, count: int) -> list[_dt.date]:
    start = end - _dt.timedelta(days=count * 3)
    rows = api_get(CALENDAR, {"from": start.isoformat(), "to": end.isoformat()}, key)
    days = sorted(
        _dt.date.fromisoformat(r["Date"])
        for r in rows
        if str(r.get("HolDiv")) in {"1", "2"}
        and _dt.date.fromisoformat(r["Date"]) <= end
    )
    if not days:
        raise RuntimeError(f"No business days found between {start} and {end}")
    return days[-count:]

def fetch_master(key: str, date: _dt.date) -> dict:
    rows = api_get(MASTER, {"date": date.isoformat()}, key)
    return {r["Code"]: r for r in rows}

def run_fetch_yesterday():
    key = load_env("JQUANTS_API_KEY")
    today = _dt.date.today()
    days = trading_days(key, today, AVG_WINDOW + 5)
    
    target_day = next((d for d in reversed(days) if d < today), None)
    if not target_day:
        print("No valid past business day found.")
        return

    target_days = [d for d in days if d <= target_day][-AVG_WINDOW:]
    print(f"Fetching data for the past {AVG_WINDOW} business days from J-Quants API...")
    
    by_symbol = {}
    for d in target_days:
        rows = api_get(BARS_DAILY, {"date": d.isoformat()}, key)
        for r in rows:
            by_symbol.setdefault(r["Code"], []).append(r)
        print(f"  {d}: Fetched {len(rows)} symbols")
        
    master = fetch_master(key, target_days[-1])
    universe = {}
    for code, bars in by_symbol.items():
        if len(bars) < AVG_WINDOW // 2:
            continue
        m = master.get(code)
        if not m or str(m.get("Mkt")) != "0111": # TSE Prime Market only
            continue
            
        valid_bars = [b for b in bars if b.get("Vo") is not None and b.get("Va") is not None]
        if valid_bars:
            avg_vo = sum(float(b["Vo"]) for b in valid_bars) / len(valid_bars)
            avg_va = sum(float(b["Va"]) for b in valid_bars) / len(valid_bars)
            c4 = code[:-1] if code.endswith("0") and len(code) == 5 else code
            universe[c4] = {
                "code": c4,
                "name": m.get("CoName", ""),
                "sector": m.get("S33Nm", ""),
                "avg_volume": avg_vo,
                "avg_turnover": avg_va,
                "latest_close": float(bars[-1].get("C", 0))
            }
            
    print(f"Universe generation complete: {len(universe)} symbols")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(UNIVERSE_FILE, "w", encoding="utf-8") as f:
        json.dump(universe, f, ensure_ascii=False, indent=2)

# =========================================================
# morning_screener (Kabutan Scraping)
# =========================================================
def _text(s: str) -> str:
    return _html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s))).strip()

def _num(s: str) -> float | None:
    s = s.replace(",", "").replace("＋", "+").replace("−", "-").strip()
    if not s or s in {"-", "－", "—"}: return None
    try: return float(s)
    except ValueError: return None

def fetch_page(url: str, cookie: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Cookie": cookie, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", "replace")

def parse_nikkei(doc: str) -> dict:
    m = re.search(r'<table id="header_shisuu_big">(.*?)</table>', doc, re.S)
    if not m: return {}
    nums = [c for c in [_text(c) for c in _CELL.findall(m.group(1))] if c and _num(c) is not None]
    if len(nums) >= 2:
        val, chg = _num(nums[0]), _num(nums[1])
        if val and chg:
            return {"value": val, "change": chg, "pct": chg / (val - chg) * 100}
    return {}

def parse_ranking(doc: str) -> list[dict]:
    m = _TABLE.search(doc)
    if not m: return []
    trs = _TR.findall(m.group(1))
    if not trs: return []
    
    rows = []
    for tr in trs[1:]:
        c = [_text(x) for x in _CELL.findall(tr)]
        if len(c) < 4: continue
        pi = next((i for i, x in enumerate(c) if x.endswith("%")), None)
        if pi is None or pi < 3: continue
            
        pct = _num(c[pi].rstrip(" %"))
        price = next((_num(c[j]) for j in range(pi - 2, 2, -1) if _num(c[j]) is not None), None)
        if price is not None:
            rows.append({"code": c[0], "name": c[1], "price": price, "change_pct": pct})
    return rows

def run_morning_screener():
    cookie = load_env("KABUTAN_COOKIE")
    if not UNIVERSE_FILE.exists():
        print(f"Error: {UNIVERSE_FILE} not found.")
        return
        
    universe = json.loads(UNIVERSE_FILE.read_text(encoding="utf-8"))
    print("Scraping today's active stocks from Kabutan...")
    all_rows = []
    nikkei = {}
    for page in range(1, MAX_PAGES + 1):
        try:
            doc = fetch_page(TARGET_URL.format(page=page), cookie)
            if page == 1: nikkei = parse_nikkei(doc)
            page_rows = parse_ranking(doc)
            all_rows.extend(page_rows)
        except Exception as e:
            print(f"  Page {page} Fetch failed: {e}")
            break
            
    n_pct = nikkei.get("pct", 0)
    if n_pct >= NIKKEI_STRONG: pick_count, regime = 5, "Bullish"
    elif n_pct <= NIKKEI_WEAK: pick_count, regime = 3, "Bearish"
    else: pick_count, regime = 4, "Neutral"
        
    print(f"\nNikkei Average: {n_pct:+.2f}% ({regime}) -> Picking {pick_count} symbols")
    
    filtered = []
    for r in all_rows:
        u = universe.get(r["code"])
        # 硬い銘柄: Turnover >= 3 billion, Price >= 500, change_pct < +5.0%
        if u and u["avg_volume"] >= MIN_AVG_VOLUME and u["avg_turnover"] >= MIN_AVG_TURNOVER and r.get("price", 0) >= 500:
            cp = r.get("change_pct", 0)
            if cp is not None and cp < 5.0:
                r.update({"avg_volume": u["avg_volume"], "avg_turnover": u["avg_turnover"], "sector": u["sector"]})
                filtered.append(r)
            
    filtered.sort(key=lambda x: -(x["change_pct"] or -99))
    targets = []
    lines = [
        f"【買い付け枠】地合い: {regime} (日経 {n_pct:+.2f}%) -> 最大 {pick_count} 銘柄を探索",
        f"条件: 出来高{MIN_AVG_VOLUME//10000}万株以上, 売買代金{MIN_AVG_TURNOVER//100000000}億円以上\n"
    ]
    
    for i, r in enumerate(filtered[:pick_count], 1):
        px = r["price"]
        shares = int((TOTAL_CAPITAL / pick_count) // px // LOT) * LOT
        if shares == 0: continue
            
        stop_px = px * (1 - SL_PCT / 100)
        target_px = px * (1 + TP_PCT / 100)
        
        targets.append({
            "code": r["code"], "name": r["name"], "sector": r["sector"],
            "entry_price": px, "shares": shares, "stop": stop_px, "target": target_px,
            "status": "OPEN", "latest_price": px
        })
        lines.append(f"{i}. {r['code']} {r['name']} ({r['sector']})\n   現在値: {px:,.1f}円 ({r['change_pct']:+.2f}%)\n   数量: {shares:,}株 (約 {px * shares / 10000:,.0f}万円)\n   利確目安(+{TP_PCT}%): {target_px:,.1f}円\n   損切目安({-SL_PCT}%): {stop_px:,.1f}円\n")
        
    if not targets: lines.append("* 本日の条件に合致する銘柄はありませんでした。")
    text = "\n".join(lines)
    
    with open(TARGETS_FILE, "w", encoding="utf-8") as f:
        json.dump({"date": _dt.date.today().isoformat(), "targets": targets}, f, ensure_ascii=False, indent=2)
    slack_post(text)
    print("Screening complete.")

# =========================================================
# intraday_monitor (Intraday Monitoring)
# =========================================================
def fetch_bulk_prices(targets: list, cookie: str) -> dict:
    codes = [t["code"] for t in targets]
    if not codes: return {}
        
    data = urllib.parse.urlencode([("codes[]", c) for c in codes]).encode("utf-8")
    req = urllib.request.Request("https://kabutan.jp/favorite/stock/", data=data,
        headers={"User-Agent": UA, "Cookie": cookie, "Accept-Encoding": "gzip", "Content-Type": "application/x-www-form-urlencoded"})
    
    prices = {}
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = gzip.decompress(r.read()) if r.headers.get("Content-Encoding") == "gzip" else r.read()
            res_json = json.loads(raw.decode("utf-8", "replace"))
            for row in (res_json if isinstance(res_json, list) else res_json.get("data", [])):
                if len(row) >= 2:
                    code, px_str = str(row[0]), str(row[1]).replace(",", "")
                    if px_str and px_str not in ["－", "-"]:
                        try: prices[code] = float(px_str)
                        except ValueError: pass
    except Exception as e:
        print(f"API Bulk Fetch Error: {e}")
    return prices

def record_trade(code: str, name: str, side: str, qty: int, price: float, pnl: float):
    trade = {"date": _dt.date.today().isoformat(), "time": _dt.datetime.now().strftime("%H:%M:%S"), "ticker": code, "name": name, "side": side, "qty": qty, "price": price, "pnl": pnl}
    history = []
    if HISTORY_FILE.exists():
        try: history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError: pass
    history.append(trade)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def run_intraday_monitor(iteration_count: int):
    if not TARGETS_FILE.exists(): return
    try: data = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    except: return
        
    if data.get("date") != _dt.date.today().isoformat(): return
        
    cookie = load_env("KABUTAN_COOKIE")
    targets = data.get("targets", [])
    updated = False
    
    try:
        prices = fetch_bulk_prices(targets, cookie)
        for t in targets:
            code = t["code"]
            px = prices.get(code)
            if px is None: continue
                
            t["latest_price"] = px
            is_history_poll = (iteration_count % 4 == 0)
            if is_history_poll:
                t.setdefault("history", [])
                current_ts = int(time.time())
                if t["history"] and t["history"][-1]["time"] >= current_ts:
                    current_ts = t["history"][-1]["time"] + 1
                t["history"].append({"time": current_ts, "value": px})
            
            updated = True
            
            # Only trigger TP/SL if the position is currently OPEN
            if t["status"] == "OPEN":
                entry_px, target_px, stop_px = t["entry_price"], t["target"], t["stop"]
                
                # Check for manual overrides from the UI
                if t.get("manual_action"):
                    action = t.pop("manual_action")
                    pnl = (px - entry_px) * t["shares"]
                    if action == "TP":
                        t["status"] = "HIT_TP"
                        record_trade(code, t['name'], "SELL(MANUAL_TP)", t["shares"], px, pnl)
                        slack_post(f"[手動利確 :tada:] {code} {t['name']}\nWEB画面より手動で利確決済されました。\n現在値: {px:,.1f} 円\n確定利益: +{pnl:,.0f} 円")
                        print(f"{code} MANUAL TP! {px}")
                    elif action == "SL":
                        t["status"] = "HIT_SL"
                        record_trade(code, t['name'], "SELL(MANUAL_SL)", t["shares"], px, pnl)
                        slack_post(f"[手動損切 :rotating_light:] {code} {t['name']}\nWEB画面より手動で損切決済されました。\n現在値: {px:,.1f} 円\n確定損失: {pnl:,.0f} 円")
                        print(f"{code} MANUAL SL! {px}")
                    updated = True
                    continue
                
                if px >= target_px:
                    t["status"] = "HIT_TP"
                    pnl = (px - entry_px) * t["shares"]
                    record_trade(code, t['name'], "SELL(TP)", t["shares"], px, pnl)
                    slack_post(f"[利確到達 :tada:] {code} {t['name']}\n現在値 {px:,.1f} 円が利確目標 ({target_px:,.1f} 円) に到達しました。\n見込利益: +{pnl:,.0f} 円")
                    print(f"{code} HIT TP! {px}")
                elif px <= stop_px:
                    now_time = _dt.datetime.now()
                    time_hm = now_time.hour * 100 + now_time.minute
                    
                    if time_hm < 945:
                        if not t.get("sl_warned"):
                            slack_post(f"[損切警告 :warning:] {code} {t['name']}\n現在値 {px:,.1f} 円が損切ライン ({stop_px:,.1f} 円) を下回りました。\n09:45まで様子見を継続します。")
                            t["sl_warned"] = True
                            print(f"{code} SL Warning triggered before 9:45.")
                    else:
                        t["status"] = "HIT_SL"
                        pnl = (px - entry_px) * t["shares"]
                        record_trade(code, t['name'], "SELL(SL)", t["shares"], px, pnl)
                        slack_post(f"[損切確定 :rotating_light:] {code} {t['name']}\n現在値 {px:,.1f} 円が損切ライン ({stop_px:,.1f} 円) に到達しました。\n見込損失: {pnl:,.0f} 円")
                        print(f"{code} HIT SL! {px}")
                
        if updated:
            with open(TARGETS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                
    except Exception as e:
        print(f"Monitor step error: {e}")

# =========================================================
# daily_report (Daily Report)
# =========================================================
def run_daily_report():
    if not TARGETS_FILE.exists(): return
    try: data = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    except: return
        
    target_date = data.get("date")
    targets = data.get("targets", [])
    total_pnl = 0
    lines = [f"【本日の運用成績レポート】 ({target_date})", "---"]
    
    if not targets:
        lines.append("本日の取引対象銘柄はありませんでした。")
    else:
        for i, t in enumerate(targets, 1):
            code, name, status, entry, shares = t["code"], t["name"], t["status"], t["entry_price"], t["shares"]
            latest = t.get("latest_price", entry)
            exit_px = latest
            
            if status == "HIT_TP": result = "🟢 利確"
            elif status == "HIT_SL": result = "🔴 損切"
            else: result = "⚪ 未決済 (大引け)"
                
            pnl = (exit_px - entry) * shares
            total_pnl += pnl
            lines.extend([f"{i}. {code} {name} - {result}", f"   エントリー: {entry:,.1f}円 -> 決済/現在値: {exit_px:,.1f}円", f"   数量: {shares:,}株", f"   損益: {pnl:+,.0f}円", ""])
            
        lines.append("---")
        lines.append(f"💰 本日の合計損益: {total_pnl:+,.0f}円")
        
    text = "\n".join(lines)
    slack_post(text)
    print("Daily report sent.")

# =========================================================
# Main Loop (Scheduler)
# =========================================================
def main():
    print("=== DayTrade Pro Master Bot Started ===")
    print("Bot is now running continuously and waiting for scheduled tasks...")
    
    iteration_count = 0
    is_monitoring = False
    
    while True:
        try:
            now = _dt.datetime.now()
            today_str = now.date().isoformat()
            time_hm = now.hour * 100 + now.minute
            
            # --- 08:30 : fetch_yesterday (Generate J-Quants Universe) ---
            if now.hour == 8 and now.minute >= 30 and get_last_run("fetch") != today_str:
                print(f"[{now.strftime('%H:%M:%S')}] Executing: run_fetch_yesterday()")
                try: run_fetch_yesterday()
                except Exception as e: print(f"fetch_yesterday Error: {e}")
                set_last_run("fetch", today_str)
                
            # --- 09:10 : morning_screener (Kabutan Screening) ---
            if now.hour == 9 and now.minute >= 10 and now.minute < 30 and get_last_run("screener") != today_str:
                print(f"[{now.strftime('%H:%M:%S')}] Executing: run_morning_screener()")
                try: run_morning_screener()
                except Exception as e: print(f"morning_screener Error: {e}")
                set_last_run("screener", today_str)
                
            # --- 08:55 ~ 11:30, 12:30 ~ 15:30 : intraday_monitor (Intraday Monitoring) ---
            if (855 <= time_hm < 1130) or (1230 <= time_hm <= 1530):
                if not is_monitoring:
                    print(f"[{now.strftime('%H:%M:%S')}] --- Monitoring Mode Started ---")
                    is_monitoring, iteration_count = True, 0
                run_intraday_monitor(iteration_count)
                iteration_count += 1
                time.sleep(15)
                continue
            else:
                if is_monitoring:
                    print(f"[{now.strftime('%H:%M:%S')}] --- Monitoring Mode Ended ---")
                    is_monitoring = False
            
            # --- 15:40 : daily_report (Daily Report) ---
            if now.hour == 15 and now.minute >= 40 and get_last_run("report") != today_str:
                print(f"[{now.strftime('%H:%M:%S')}] Executing: run_daily_report()")
                try: run_daily_report()
                except Exception as e: print(f"daily_report Error: {e}")
                set_last_run("report", today_str)
                
            time.sleep(1)
            
        except KeyboardInterrupt:
            print("Bot stopped manually.")
            sys.exit(0)
        except Exception as e:
            print(f"Master Bot Main Loop Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
