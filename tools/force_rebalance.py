import json
import datetime
from pathlib import Path

ROOT = Path("/home/shogo/DayTrade_Pro")
TARGETS_FILE = ROOT / "data" / "today_targets.json"
HISTORY_FILE = ROOT / "data" / "trade_history.json"

def record_trade(code: str, name: str, side: str, qty: int, price: float, pnl: float):
    trade = {"date": datetime.date.today().isoformat(), "time": datetime.datetime.now().strftime("%H:%M:%S"), "ticker": code, "name": name, "side": side, "qty": qty, "price": price, "pnl": pnl}
    history = []
    if HISTORY_FILE.exists():
        try: history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError: pass
    history.append(trade)
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

if not TARGETS_FILE.exists():
    print("No targets file")
    exit()

data = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
open_targets = [t for t in data.get("targets", []) if t.get("status") == "OPEN"]
num_targets = len(open_targets)

if num_targets == 0:
    print("No open targets")
    exit()

target_allocation = 10_000_000 / num_targets

for t in open_targets:
    current_px = t.get("latest_price", t.get("entry_price"))
    new_shares = int(target_allocation // current_px // 100) * 100
    if new_shares == 0: new_shares = 100
    
    if new_shares < t["shares"]:
        shares_to_sell = t["shares"] - new_shares
        pnl = (current_px - t["entry_price"]) * shares_to_sell
        record_trade(t["code"], t["name"], "SELL(REBALANCE)", shares_to_sell, current_px, pnl)
        t["shares"] = new_shares
        print(f"Rebalanced {t['code']}: sold {shares_to_sell} shares at {current_px}, PnL {pnl}, new shares: {new_shares}")

TARGETS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print("Done rebalancing.")
