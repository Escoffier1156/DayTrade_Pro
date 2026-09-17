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
TARGET_URL = "https://kabutan.jp/stock/?code=0000"
# [/LOCK]
MIN_AVG_VOLUME = 400_000
MIN_AVG_TURNOVER = 3_000_000_000
TP_PCT = 1.0
SL_PCT = 2.0
NIKKEI_STRONG = 0.5
NIKKEI_WEAK = -0.5
def get_total_capital():
    base = 10_000_000
    if HISTORY_FILE.exists():
        try:
            history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            base += sum(t.get("pnl", 0) for t in history)
        except: pass
    return base
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
                "latest_close": float(bars[-1].get("C") or 0)
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
    matches = re.finditer(r'<h2 class="title2">寄与度上位10</h2>.*?<tbody>(.*?)</tbody>', doc, re.S)
    rows = []
    for m in matches:
        trs = re.findall(r'<tr>(.*?)</tr>', m.group(1), re.S)
        for tr in trs:
            code_name = re.search(r'<a href="/stock/\?code=(\w+)">([^<]+)</a>', tr)
            price_m = re.findall(r'<td>([\d,.]+)</td>', tr)
            pct_m = re.search(r'<td class="w50">.*?([+-][\d.]+)</span>%', tr)
            if code_name and len(price_m) >= 1 and pct_m:
                code, name = code_name.groups()
                price = float(price_m[0].replace(",", ""))
                pct = float(pct_m.group(1))
                rows.append({"code": code, "name": name, "price": price, "change_pct": pct})
    return rows

def run_morning_screener():
    cookie = load_env("KABUTAN_COOKIE")
    if not UNIVERSE_FILE.exists():
        print(f"Error: {UNIVERSE_FILE} not found.")
        return
        
    universe = json.loads(UNIVERSE_FILE.read_text(encoding="utf-8"))
    print("Scraping Nikkei Average top contributors...")
    nikkei = {}
    all_rows = []
    try:
        doc = fetch_page(TARGET_URL, cookie)
        nikkei = parse_nikkei(doc)
        all_rows = parse_ranking(doc)
    except Exception as e:
        print(f"  URL {TARGET_URL} Fetch failed: {e}")
            
    n_pct = nikkei.get("pct", 0)
    if n_pct >= NIKKEI_STRONG: pick_count, regime = 5, "Bullish"
    elif n_pct <= NIKKEI_WEAK: pick_count, regime = 3, "Bearish"
    else: pick_count, regime = 4, "Neutral"
        
    print(f"\nNikkei Average: {n_pct:+.2f}% ({regime}) -> Picking {pick_count} symbols")
    
    # [LOCK: strict]
    filtered = []
    for r in all_rows:
        u = universe.get(r["code"])
        sector = u["sector"] if u else "日経225"
        r["sector"] = sector
        filtered.append(r)
    # [/LOCK]
    
    boss = None
    if all_rows:
        if regime == "Bearish" and len(all_rows) > 10:
            boss = all_rows[10]
        else:
            boss = all_rows[0]
            
    filtered.sort(key=lambda x: -(abs(x.get("change_pct") or 0)))
    targets = []
    lines = [
        f"【買い付け枠】地合い: {regime} (日経 {n_pct:+.2f}%) -> 少数精鋭(最大3銘柄)を抽出\n",
        f"※主役銘柄（寄与度トップ）と値がさ株を優先して組み込みます\n"
    ]
    
    print("Fetching real-time prices for top candidates to prevent lag-based bad picks...")
    top_cands = filtered[:15]
    live_prices = fetch_bulk_prices(top_cands, cookie)
    
    verified_filtered = []
    for r in top_cands:
        code = r["code"]
        if code in live_prices:
            live_px = live_prices[code]
            u = universe.get(code)
            if u and u.get("latest_close"):
                real_pct = (live_px - u["latest_close"]) / u["latest_close"] * 100
                r["price"] = live_px
                r["change_pct"] = real_pct
                
                if regime == "Bullish" and real_pct <= 0:
                    continue
                elif regime == "Bearish" and real_pct >= 0:
                    continue
                
                verified_filtered.append(r)
                
    verified_filtered.sort(key=lambda x: -(abs(x.get("change_pct") or 0)))
    
    new_boss = verified_filtered[0] if verified_filtered else None
    
    accepted = []
    if new_boss:
        accepted.append(new_boss)
        
    high_priced_cands = [r for r in verified_filtered if r.get("price", 0) >= 30000 and r["code"] != (new_boss["code"] if new_boss else "")]
    if high_priced_cands:
        accepted.append(high_priced_cands[0])
            
    normal_cands = [r for r in verified_filtered if r["code"] not in [a["code"] for a in accepted]]
    for r in normal_cands:
        if len(accepted) >= 3:
            break
        if r.get("price", 0) > 0:
            accepted.append(r)
            
    # Calculate base cost and new_shares with live prices
    base_cost = 0
    final_accepted = []
    total_cap = get_total_capital()
    for a in accepted:
        if base_cost + a["price"] * LOT <= total_cap:
            base_cost += a["price"] * LOT
            a["new_shares"] = LOT
            final_accepted.append(a)
    accepted = final_accepted
            
    # 2. Distribute remaining capital dynamically to balance the position size
    remaining = total_cap - base_cost
    while remaining > 0:
        candidates = [r for r in accepted if r["price"] * LOT <= remaining]
        if not candidates:
            break
        best = min(candidates, key=lambda r: r["price"] * r["new_shares"])
        best["new_shares"] += LOT
        remaining -= best["price"] * LOT
    
    for i, r in enumerate(accepted, 1):
        px = r["price"]
        shares = r.pop("new_shares")
        
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
        
        # Reload TARGETS_FILE to catch any manual_action added by server.py during the network fetch
        try:
            latest_data = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
            latest_targets = {t["code"]: t for t in latest_data.get("targets", [])}
            for t in targets:
                if t["code"] in latest_targets and "manual_action" in latest_targets[t["code"]]:
                    t["manual_action"] = latest_targets[t["code"]]["manual_action"]
                    if "action_price" in latest_targets[t["code"]]:
                        t["action_price"] = latest_targets[t["code"]]["action_price"]
        except Exception as e:
            print(f"Failed to reload targets for manual_action: {e}")
            
        for t in targets:
            code = t["code"]
            px = prices.get(code)
            if px is None: continue
                
            t["latest_price"] = px
            
            # Update history (chart) every 1 minute, but keep the latest value real-time (15s)
            t.setdefault("history", [])
            now_dt = _dt.datetime.now()
            current_minute_ts = int(now_dt.replace(second=0, microsecond=0).timestamp())
            
            if not t["history"] or t["history"][-1]["time"] < current_minute_ts:
                t["history"].append({"time": current_minute_ts, "value": px})
            
            updated = True
            
            # Check for manual overrides from the UI
            if t.get("manual_action"):
                action = t.pop("manual_action")
                exec_px = t.pop("action_price", px)
                pnl = (exec_px - t["entry_price"]) * t["shares"] if exec_px else 0
                
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
                        record_trade(code, t['name'], "SELL(MANUAL_TP)", t["shares"], exec_px, pnl)
                        slack_post(f"[手動利確] {code} {t['name']}\n実行時間: {now_str}\n買値(エントリー): {t['entry_price']:,.1f} 円\n売値(現在値): {exec_px:,.1f} 円\n確定利益: +{pnl:,.0f} 円")
                        print(f"{code} MANUAL TP! {exec_px}")
                        updated = True
                    elif action == "SL":
                        t["status"] = "HIT_SL"
                        now_str = _dt.datetime.now().strftime('%H:%M:%S')
                        record_trade(code, t['name'], "SELL(MANUAL_SL)", t["shares"], exec_px, pnl)
                        slack_post(f"[手動損切] {code} {t['name']}\n実行時間: {now_str}\n買値(エントリー): {t['entry_price']:,.1f} 円\n売値(現在値): {exec_px:,.1f} 円\n確定損失: {pnl:,.0f} 円")
                        print(f"{code} MANUAL SL! {exec_px}")
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
                        updated = True
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
            
            time.sleep(1)
            
        except KeyboardInterrupt:
            print("Bot stopped manually.")
            sys.exit(0)
        except Exception as e:
            print(f"Master Bot Main Loop Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
