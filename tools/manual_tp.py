import json

path = "/home/shogo/DayTrade_Pro/data/today_targets.json"
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

for t in data["targets"]:
    if t["code"] in ["5711", "5714"]:
        # Set target to 0 to force TP trigger on next tick
        t["target"] = 0

with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("Modified today_targets.json")
