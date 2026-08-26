import urllib.request
import re

req = urllib.request.Request("https://kabutan.jp/stock/?code=7203", headers={"User-Agent": "Mozilla/5.0"})
doc = urllib.request.urlopen(req).read().decode("utf-8")
start = doc.find('id="kobetsu_left"')
end = doc.find('<!--PTS-->', start)
block = doc[start:end]

for line in block.splitlines():
    if "VWAP" in line.upper():
        print(line)
