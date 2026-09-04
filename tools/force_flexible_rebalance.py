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

if not TARGETS_FILE.exists(): exit()

data = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
open_targets = [t for t in data.get("targets", []) if t.get("status") == "OPEN"]

# Add 285A back as if it was newly added
new_target = {
  "code": "285A",
  "name": "キオクシアホールディングス（キオクシア）",
  "sector": "Unknown",
  "entry_price": 53840.0,
  "shares": 0,
  "stop": 52763.2,
  "target": 54647.6,
  "status": "OPEN",
  "latest_price": 53950.0,
  "history": []
}
all_targets = open_targets + [new_target]

# 1. Base allocation of 100 shares
base_cost = 0
for t in all_targets:
    current_px = t.get("latest_price", t.get("entry_price"))
    base_cost += current_px * 100
    t["new_shares"] = 100

if base_cost > 10_000_000:
    print("Cannot fit even minimum shares.")
    exit()

# 2. Distribute remaining capital
remaining = 10_000_000 - base_cost
while remaining > 0:
    candidates = []
    for t in all_targets:
        current_px = t.get("latest_price", t.get("entry_price"))
        if current_px * 100 <= remaining:
            candidates.append(t)
    if not candidates:
        break
        
    best = min(candidates, key=lambda t: t.get("latest_price", t.get("entry_price")) * t["new_shares"])
    current_px = best.get("latest_price", best.get("entry_price"))
    best["new_shares"] += 100
    remaining -= current_px * 100

# 3. Apply rebalancing to existing targets
for t in open_targets:
    if t["new_shares"] < t["shares"]:
        shares_to_sell = t["shares"] - t["new_shares"]
        current_px = t.get("latest_price", t.get("entry_price"))
        pnl = (current_px - t["entry_price"]) * shares_to_sell
        record_trade(t["code"], t["name"], "SELL(REBALANCE)", shares_to_sell, current_px, pnl)
        print(f"Sold {shares_to_sell} of {t['code']}")
    t["shares"] = t.pop("new_shares")

# 4. Finalize new target
new_target["shares"] = new_target.pop("new_shares")
data.setdefault("targets", []).append(new_target)

TARGETS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print("Flexible rebalance applied and 285A restored!")
