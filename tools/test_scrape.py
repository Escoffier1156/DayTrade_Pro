import urllib.request
import re

def extract_details(doc: str) -> dict:
    details = {}
    
    start = doc.find('id="kobetsu_left"')
    if start < 0:
        print("kobetsu_left not found")
        return details
    end = doc.find('<!--PTS-->', start)
    if end < 0:
        end = len(doc)
    block = doc[start:end]
    
    def get_val(th_text):
        m = re.search(r"<th[^>]*>(?:<[^>]+>)*\s*" + th_text + r"\s*(?:</[^>]+>)*</th>\s*<td[^>]*>(.*?)</td>", block, re.S)
        if m:
            s = re.sub(r"<[^>]+>", "", m.group(1)).replace("&nbsp;", "").replace(",", "").replace("株", "").replace("円", "").replace("回", "").replace("百万", "").strip()
            print(f"Found {th_text}: '{s}'")
            if s == "－" or s == "-":
                return None
            try:
                return float(s)
            except ValueError:
                return None
        else:
            print(f"{th_text} regex not found")
        return None
        
    details["volume"] = get_val("出来高")
    details["turnover"] = get_val("売買代金")
    details["vwap"] = get_val("VWAP")
    details["trades"] = get_val("約定回数")
    return details

req = urllib.request.Request("https://kabutan.jp/stock/?code=7203", headers={"User-Agent": "Mozilla/5.0"})
doc = urllib.request.urlopen(req).read().decode("utf-8")
print(extract_details(doc))
