import json
import re

har_path = "kabutan.jp_favorite_stock__Archive [26-09-09 09-00-57].har"
with open(har_path) as f:
    har = json.load(f)

cookie_str = ""
for entry in har.get("log", {}).get("entries", []):
    req = entry.get("request", {})
    if "kabutan.jp" in req.get("url", ""):
        for header in req.get("headers", []):
            if header.get("name", "").lower() == "cookie":
                if "_oboe_jwt" in header.get("value", ""):
                    cookie_str = header.get("value", "")
                    break
        if cookie_str:
            break

if not cookie_str:
    print("Could not find kabutan cookie in HAR")
else:
    print("Found cookie!")
    env_path = "config/secrets.env"
    with open(env_path) as f:
        env = f.read()
    
    new_env = re.sub(r"KABUTAN_COOKIE=.*", f"KABUTAN_COOKIE={cookie_str}", env)
    
    with open(env_path, "w") as f:
        f.write(new_env)
    print("secrets.env updated successfully.")
