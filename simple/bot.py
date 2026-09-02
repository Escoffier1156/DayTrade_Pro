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

# [LOCK: strict]
# Kabutan Screener
TARGET_URLS = [
    "https://kabutan.jp/warning/?mode=2_9",
    "https://kabutan.jp/warning/?mode=2_9&market=0&capitalization=-1&dispmode=normal&stc=&stm=0&page=2",
    "https://kabutan.jp/warning/?mode=2_9&market=0&capitalization=-1&dispmode=normal&stc=&stm=0&page=3",
    "https://kabutan.jp/warning/?mode=2_9&market=0&capitalization=-1&dispmode=normal&stc=&stm=0&page=4",
    "https://kabutan.jp/warning/?mode=2_9&capitalization=3&dispmode=normal",
    "https://kabutan.jp/warning/?mode=2_9&market=0&capitalization=3&dispmode=normal&stc=&stm=0&page=2",
    "https://kabutan.jp/warning/?mode=2_9&market=0&capitalization=3&dispmode=normal&stc=&stm=0&page=3"
]
# [/LOCK]
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
    for i, url in enumerate(TARGET_URLS):
        try:
            doc = fetch_page(url, cookie)
            if i == 0: nikkei = parse_nikkei(doc)
            page_rows = parse_ranking(doc)
            all_rows.extend(page_rows)
        except Exception as e:
            print(f"  URL {url} Fetch failed: {e}")
            
    n_pct = nikkei.get("pct", 0)
    if n_pct >= NIKKEI_STRONG: pick_count, regime = 5, "Bullish"
    elif n_pct <= NIKKEI_WEAK: pick_count, regime = 3, "Bearish"
    else: pick_count, regime = 4, "Neutral"
        
    print(f"\nNikkei Average: {n_pct:+.2f}% ({regime}) -> Picking {pick_count} symbols")
    
    # [LOCK: strict]
    filtered = []
    for r in all_rows:
        u = universe.get(r["code"])
        # 硬い銘柄: Turnover >= 3 billion, Price >= 500, 0.0% <= change_pct < +5.0%
        if u and u["avg_volume"] >= MIN_AVG_VOLUME and u["avg_turnover"] >= MIN_AVG_TURNOVER and r.get("price", 0) >= 500:
            cp = r.get("change_pct", 0)
            if cp is not None and 0.0 <= cp < 5.0:
                r.update({"avg_volume": u["avg_volume"], "avg_turnover": u["avg_turnover"], "sector": u["sector"]})
                filtered.append(r)
            
    filtered.sort(key=lambda x: -(x["change_pct"] or -99))
    # [/LOCK]
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
    prices = {}
    for t in targets:
        code = t["code"]
        url = f"https://kabutan.jp/stock/?code={code}"
        headers = {"User-Agent": UA}
        if cookie:
            headers["Cookie"] = cookie
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                html = r.read().decode("utf-8", "replace")
                m = re.search(r'<span class="kabuka">([\d,.]+)円</span>', html)
                if m:
                    prices[code] = float(m.group(1).replace(",", ""))
            time.sleep(1)
        except Exception as e:
            print(f"[{code}] Fetch Error: {e}")
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

def remove_trade(code: str, side_prefix: str):
    if not HISTORY_FILE.exists(): return
    try: history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except: return
    new_history = []
    removed = False
    today = _dt.date.today().isoformat()
    for h in history:
        if not removed and h.get("ticker") == code and h.get("side", "").startswith(side_prefix) and h.get("date") == today:
            removed = True
            continue
        new_history.append(h)
    if removed:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(new_history, f, ensure_ascii=False, indent=2)

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
            
            # Update history (chart) every 15 seconds (real-time)
            is_history_poll = True
            if is_history_poll:
                t.setdefault("history", [])
                current_ts = int(time.time())
                if t["history"] and t["history"][-1]["time"] >= current_ts:
                    current_ts = t["history"][-1]["time"] + 1
                t["history"].append({"time": current_ts, "value": px})
            
            updated = True
            
            # Check for manual overrides from the UI
            if t.get("manual_action"):
                action = t.pop("manual_action")
                pnl = (px - t["entry_price"]) * t["shares"] if px else 0
                
                if action == "CANCEL_TP" and t["status"] == "HIT_TP":
                    t["status"] = "OPEN"
                    if "tp_warned" in t:
                        del t["tp_warned"]
                    remove_trade(code, "SELL(MANUAL_TP)")
                    updated = True
                    print(f"{code} CANCEL TP processed.")
                    
                elif t["status"] == "OPEN":
                    if action == "TP":
                        t["status"] = "HIT_TP"
                        now_str = _dt.datetime.now().strftime('%H:%M:%S')
                        record_trade(code, t['name'], "SELL(MANUAL_TP)", t["shares"], px, pnl)
                        slack_post(f"[手動利確] {code} {t['name']}\n実行時間: {now_str}\n買値(エントリー): {t['entry_price']:,.1f} 円\n売値(現在値): {px:,.1f} 円\n確定利益: +{pnl:,.0f} 円")
                        print(f"{code} MANUAL TP! {px}")
                        updated = True
                    elif action == "SL":
                        t["status"] = "HIT_SL"
                        now_str = _dt.datetime.now().strftime('%H:%M:%S')
                        record_trade(code, t['name'], "SELL(MANUAL_SL)", t["shares"], px, pnl)
                        slack_post(f"[手動損切] {code} {t['name']}\n実行時間: {now_str}\n買値(エントリー): {t['entry_price']:,.1f} 円\n売値(現在値): {px:,.1f} 円\n確定損失: {pnl:,.0f} 円")
                        print(f"{code} MANUAL SL! {px}")
                        updated = True
                continue
            
            # Only trigger TP/SL if the position is currently OPEN
            if t["status"] == "OPEN":
                entry_px, target_px, stop_px = t["entry_price"], t["target"], t["stop"]
                
                if px >= target_px:
                    if not t.get("tp_warned"):
                        now_str = _dt.datetime.now().strftime('%H:%M:%S')
                        slack_post(f"[利確アラート] {code} {t['name']}\n到達時間: {now_str}\n買値(エントリー): {entry_px:,.1f} 円\n現在値: {px:,.1f} 円\n利確ライン ({target_px:,.1f} 円) を上回りました。\n※自動決済は停止中です。Web画面から手動で判断してください。")
                        t["tp_warned"] = True
                        print(f"{code} TP Alert triggered (Notification only).")
                elif px <= stop_px:
                    if not t.get("sl_warned"):
                        now_str = _dt.datetime.now().strftime('%H:%M:%S')
                        slack_post(f"[損切アラート] {code} {t['name']}\n到達時間: {now_str}\n買値(エントリー): {entry_px:,.1f} 円\n現在値: {px:,.1f} 円\n損切ライン ({stop_px:,.1f} 円) を下回りました。\n※自動決済は停止中です。Web画面から手動で判断してください。")
                        t["sl_warned"] = True
                        print(f"{code} SL Alert triggered (Notification only).")
                
        if updated:
            with open(TARGETS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                
    except Exception as e:
        print(f"Monitor step error: {e}")



# =========================================================
# daily_report (Daily Report)
# =========================================================
def run_daily_report():
    import datetime
    target_date = datetime.date.today().isoformat()
    lines = [f"【本日の運用成績レポート】 ({target_date})", "---"]
    total_realized_pnl = 0
    total_unrealized_pnl = 0
    
    history_data = []
    if HISTORY_FILE.exists():
        try:
            all_history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            history_data = [h for h in all_history if h.get("date") == target_date]
        except Exception:
            pass
    
    lines.append("■ 決済済 (実現損益)")
    if not history_data:
        lines.append("本日の決済済み銘柄はありません。")
    else:
        for i, h in enumerate(history_data, 1):
            side_str = str(h.get("side", ""))
            if "TP" in side_str:
                result = "利確"
            elif "SL" in side_str:
                result = "損切"
            elif "PARTIAL" in side_str:
                result = "部分決済"
            else:
                result = side_str
            pnl = float(h.get("pnl", 0))
            total_realized_pnl += pnl
            lines.extend([
                f"{i}. {h.get('time', '')} {h.get('ticker', '')} {h.get('name', '')} - {result}",
                f"   数量: {h.get('qty', 0):,}株 / 決済値: {h.get('price', 0):,.1f}円",
                f"   損益: {pnl:+,.0f}円"
            ])
    
    lines.append("")
    lines.append("■ 保有中 (含み損益)")
    
    targets_data = []
    if TARGETS_FILE.exists():
        try:
            tdata = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
            if tdata.get("date") == target_date:
                targets_data = tdata.get("targets", [])
        except Exception:
            pass
    
    open_targets = [t for t in targets_data if t.get("status") == "OPEN"]
    
    if not open_targets:
        lines.append("現在保有中の銘柄はありません。")
    else:
        for i, t in enumerate(open_targets, 1):
            code, name, entry, shares = t.get("code"), t.get("name"), float(t.get("entry_price", 0)), int(t.get("shares", 0))
            current_px = float(t.get("latest_price", entry))
            pnl = (current_px - entry) * shares
            total_unrealized_pnl += pnl
            lines.extend([
                f"{i}. {code} {name}",
                f"   数量: {shares:,}株 / エントリー: {entry:,.1f}円 -> 現在値: {current_px:,.1f}円",
                f"   含み損益: {pnl:+,.0f}円"
            ])
    
    lines.append("---")
    lines.append("【本日の合計】")
    lines.append(f"実現損益: {total_realized_pnl:+,.0f}円")
    lines.append(f"含み損益: {total_unrealized_pnl:+,.0f}円")
    
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
            
            # Skip execution on weekends (Saturday=5, Sunday=6)
            if now.weekday() >= 5:
                time.sleep(60)
                continue
                
            # [LOCK: strict]
            # --- 08:55 : fetch_yesterday (Generate J-Quants Universe) ---
            if now.hour == 8 and now.minute >= 55 and get_last_run("fetch") != today_str:
                print(f"[{now.strftime('%H:%M:%S')}] Executing: run_fetch_yesterday()")
                try: run_fetch_yesterday()
                except Exception as e: print(f"fetch_yesterday Error: {e}")
                set_last_run("fetch", today_str)
                
            # --- 09:10 : morning_screener (Kabutan Screening) ---
            if now.hour == 9 and now.minute >= 10 and now.minute < 30 and get_last_run("screener") != today_str:
                print(f"[{now.strftime('%H:%M:%S')}] Executing: run_morning_screener()")
                try: run_morning_screener()
                except Exception as e: print(f"morning_screener Error: {e}")
            # [/LOCK]
                set_last_run("screener", today_str)
                
            # --- 08:55 ~ 15:30 : intraday_monitor (Intraday Monitoring) ---
            if 855 <= time_hm <= 1530:
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
            if STATE_FILE.exists():
                try:
                    state_data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                    if state_data.get("trigger_report"):
                        print(f"[{now.strftime('%H:%M:%S')}] Manual Trigger: Executing run_daily_report()")
                        try: run_daily_report()
                        except Exception as e: print(f"daily_report Error: {e}")
                        state_data["trigger_report"] = False
                        STATE_FILE.write_text(json.dumps(state_data, ensure_ascii=False, indent=2), encoding="utf-8")
                except Exception as e:
                    print(f"Failed to check manual triggers: {e}")
            
            time.sleep(1)
            
        except KeyboardInterrupt:
            print("Bot stopped manually.")
            sys.exit(0)
        except Exception as e:
            print(f"Master Bot Main Loop Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
