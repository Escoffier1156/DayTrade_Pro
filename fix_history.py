import json

path = "data/trade_history.json"
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

# Keep only real trades (not Mock)
filtered = [d for d in data if not d["name"].startswith("Mock")]

with open(path, "w", encoding="utf-8") as f:
    json.dump(filtered, f, ensure_ascii=False, indent=2)

print("Removed mock data")
