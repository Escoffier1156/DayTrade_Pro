import json

path = "data/today_targets.json"
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

for t in data["targets"]:
    if t["code"] == "4568":
        # Set stop to 99999 to force SL trigger on next tick
        t["stop"] = 99999

with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("Modified today_targets.json for Daiichi Sankyo")
