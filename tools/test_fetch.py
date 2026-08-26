import sys, json, urllib.request, urllib.parse, gzip
sys.path.append("/home/shogo/DayTrade_Pro/simple")
from intraday_monitor import load_env, UA
cookie = load_env("KABUTAN_COOKIE")

url = "https://kabutan.jp/favorite/stock/"
query = [("codes[]", "5711"), ("codes[]", "5714"), ("codes[]", "9501")]
data = urllib.parse.urlencode(query).encode("utf-8")
req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Cookie": cookie, "Accept-Encoding": "gzip", "Content-Type": "application/x-www-form-urlencoded"})

with urllib.request.urlopen(req, timeout=15) as r:
    raw = r.read()
    if r.headers.get("Content-Encoding") == "gzip":
        raw = gzip.decompress(raw)
    res_text = raw.decode("utf-8", "replace")
    print("RESPONSE:", res_text[:200])
