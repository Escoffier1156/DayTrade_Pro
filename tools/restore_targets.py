import json

targets_file = "data/today_targets.json"
data = json.load(open(targets_file))

# Add 9983 back
data["targets"].append({
  "code": "9983",
  "name": "ファーストリテイリング（ファストリ）",
  "sector": "Unknown",
  "entry_price": 68990.0,
  "shares": 100,
  "stop": 67610.2,
  "target": 70024.85,
  "status": "OPEN",
  "latest_price": 69360.0,
  "history": []
})

# Add 285A back
data["targets"].append({
  "code": "285A",
  "name": "キオクシアホールディングス（キオクシア）",
  "sector": "Unknown",
  "entry_price": 53840.0,
  "shares": 100,
  "stop": 52763.2,
  "target": 54647.6,
  "status": "OPEN",
  "latest_price": 53950.0,
  "history": []
})

with open(targets_file, "w") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print("Restored!")
