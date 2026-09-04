import json
from pathlib import Path

ROOT = Path("/home/shogo/DayTrade_Pro")
TARGETS_FILE = ROOT / "data" / "today_targets.json"

if not TARGETS_FILE.exists(): exit()

data = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
all_targets = data.get("targets", [])

# Fixed cost of CLOSED targets
closed_cost = 0
open_targets = []
for t in all_targets:
    if t.get("status") != "OPEN":
        closed_cost += t.get("entry_price", 0) * t.get("shares", 0)
    else:
        open_targets.append(t)

print(f"Closed cost: {closed_cost}")

# 1. Base allocation for OPEN targets
base_cost = closed_cost
for t in open_targets:
    current_px = t.get("latest_price", t.get("entry_price"))
    base_cost += current_px * 100
    t["new_shares"] = 100

if base_cost > 10_000_000:
    print("Cannot fit even minimum shares.")
    exit()

# 2. Distribute remaining capital among OPEN targets
remaining = 10_000_000 - base_cost
while remaining > 0:
    candidates = []
    for t in open_targets:
        current_px = t.get("latest_price", t.get("entry_price"))
        if current_px * 100 <= remaining:
            candidates.append(t)
    if not candidates:
        break
        
    best = min(candidates, key=lambda t: t.get("latest_price", t.get("entry_price")) * t["new_shares"])
    current_px = best.get("latest_price", best.get("entry_price"))
    best["new_shares"] += 100
    remaining -= current_px * 100

# 3. Apply rebalancing to OPEN targets (no history recording for this one-off fix to avoid fake PnL again, just adjust shares)
for t in open_targets:
    t["shares"] = t.pop("new_shares")
    print(f"Set {t['code']} to {t['shares']} shares.")

TARGETS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print("Fixed total allocation including closed targets.")
