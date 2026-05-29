#!/usr/bin/env python3
"""Fetch A-share stock concepts from 同花顺问财 API and save as CSV."""

import json
import time
import urllib.request
import urllib.parse
import ssl
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

QUESTION = "给我导出所有A股的概念板块的csv"
PERPAGE = 100
OUTPUT = "/Users/hg26502/claude/stock/export/data/stock_concepts.csv"

def fetch_page(hexin_v, page=1, perpage=50):
    url = "https://www.iwencai.com/unifiedwap/unified-wap/v2/result/get-robot-data"
    data = urllib.parse.urlencode({
        "source": "Ths_iwencai_Xuangu",
        "version": "2.0",
        "question": QUESTION,
        "secondary_intent": "stock",
        "perpage": str(perpage),
        "page": str(page),
        "add_info": json.dumps({
            "urp": {"scene": 1, "company": 1, "business": 1},
            "contentType": "json",
            "searchInfo": True
        }),
        "rsh": "Ths_iwencai_Xuangu_7b597aen4yul7kg5mv4kyazk02lkr2b3"
    }).encode()

    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("hexin-v", hexin_v)
    req.add_header("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36")

    try:
        resp = urllib.request.urlopen(req, context=ssl_ctx)
        body = json.loads(resp.read())
        comp = body["data"]["answer"][0]["txt"][0]["content"]["components"][0]
        datas = comp["data"]["datas"]
        meta = comp["data"]["meta"]
        return datas, meta
    except Exception as e:
        print(f"Error on page {page}: {e}")
        return None, None


def main():
    # Fresh hexin-v from a browser session
    hexin_v = "A07eROSaqKr7exyOGPL46_eDmS8VzxLJJJPGrXiXutEM2-CR4F9i2fQjFrdL"

    all_stocks = {}
    page = 1

    while True:
        datas, meta = fetch_page(hexin_v, page, PERPAGE)
        if not datas or len(datas) == 0:
            break

        for d in datas:
            code = d.get("股票代码", "")
            if code:
                all_stocks[code] = {
                    "name": d.get("股票简称", ""),
                    "concepts": d.get("所属概念", ""),
                    "count": d.get("所属概念数量", 0),
                }

        print(f"Page {page}: got {len(datas)} stocks, {len(all_stocks)} unique so far")

        if len(datas) < PERPAGE:
            break

        page += 1
        time.sleep(0.5)

    # Write CSV
    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write("stock_code,stock_name,concepts,concept_count\n")
        for code in sorted(all_stocks.keys()):
            s = all_stocks[code]
            name = s["name"].replace('"', '""')
            concepts = s["concepts"].replace('"', '""')
            f.write(f'{code},"{name}","{concepts}",{s["count"]}\n')

    print(f"\nDone: {len(all_stocks)} stocks saved to {OUTPUT}")


if __name__ == "__main__":
    main()
