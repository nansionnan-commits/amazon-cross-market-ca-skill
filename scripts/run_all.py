# -*- coding: utf-8 -*-
"""亚马逊跨站复制 Listing 一键入口（US → CA）。

用法：
  python run_all.py B0XXX,B0YYY,B0ZZZ    给定 US 站 ASIN（逗号分隔，可含父/子/独立）
  python run_all.py --today              自动抓 US 站当天(UTC)新上架

流程：反查 SKU/PT → 父子分组 → 构建 CA patch → 上传(先父后子) → 回验
铁律已固化在 batch_ca.py：乘数 1.38 / language_tag en_CA / 品牌 Generic /
变体 COLOR / 库存 500 / 处理 2 天 / GTIN 豁免 / 图片 CDN 透传。
"""
import json
import sys
import time
import urllib.parse
from datetime import datetime, timezone

import auth
import batch_ca as bc


# ---------- 1. 反查 US 站 listing（asin->sku, sku->pt） ----------
def search_us_listings():
    asin2sku, sku2pt = {}, {}
    token = None
    while True:
        params = {"marketplaceIds": auth.US, "pageSize": 20,
                  "includedData": "summaries", "sortBy": "createdDate", "sortOrder": "DESC"}
        if token:
            params["pageToken"] = token
        qs = urllib.parse.urlencode(params)
        st, r = auth.request("GET", f"/listings/2021-08-01/items/{auth.SELLER_ID}?{qs}")
        if st != 200:
            break
        for it in r.get("items", []):
            summ = (it.get("summaries") or [{}])[0]
            sku, asin = it.get("sku"), summ.get("asin")
            if sku and asin:
                asin2sku[asin] = sku
                sku2pt[sku] = summ.get("productType")
        token = (r.get("pagination") or {}).get("nextToken")
        if not token:
            break
    return asin2sku, sku2pt


# ---------- 2. 抓当天新上架 ASIN ----------
def fetch_today_asins():
    created_after = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
    asins = []
    token = None
    while True:
        params = {"marketplaceIds": auth.US, "pageSize": 20, "includedData": "summaries",
                  "sortBy": "createdDate", "sortOrder": "DESC", "createdAfter": created_after}
        if token:
            params["pageToken"] = token
        qs = urllib.parse.urlencode(params)
        st, r = auth.request("GET", f"/listings/2021-08-01/items/{auth.SELLER_ID}?{qs}")
        if st != 200:
            break
        for it in r.get("items", []):
            summ = (it.get("summaries") or [{}])[0]
            if summ.get("asin"):
                asins.append(summ["asin"])
        token = (r.get("pagination") or {}).get("nextToken")
        if not token:
            break
    return asins


# ---------- 3. 父子关系 ----------
def get_relationships(asin):
    qs = urllib.parse.urlencode({"marketplaceIds": auth.US, "includedData": "relationships"})
    st, r = auth.request("GET", f"/catalog/2022-04-01/items/{asin}?{qs}")
    children, parent = [], None
    for mp in r.get("relationships", []):
        for rel in mp.get("relationships", []):
            if rel.get("type") == "VARIATION":
                if rel.get("childAsins"):
                    children = rel["childAsins"]
                if rel.get("parentAsin"):
                    parent = rel["parentAsin"]
    return children, parent


# ---------- 4. 分组 ----------
def resolve_groups(asins, asin2sku, sku2pt):
    """把 ASIN 列表解析成变体组。返回 [{parent_sku, pt, children:[子sku], standalone:bool}]。"""
    children_of, parent_of = {}, {}
    queue = list(asins)
    for a in queue:
        if a not in asin2sku:
            continue
        ch, par = get_relationships(a)
        if ch:
            children_of[a] = ch
            for c in ch:
                parent_of[c] = a
        if par:
            parent_of[a] = par

    groups = []
    seen_child = set()
    # 变体组（父 + 子）
    for a, ch in children_of.items():
        if a not in asin2sku:
            continue
        cskus = [asin2sku[c] for c in ch if c in asin2sku]
        groups.append({"parent_sku": asin2sku[a], "pt": sku2pt.get(asin2sku[a]),
                       "children": cskus, "standalone": False})
        seen_child.update(ch)
    # 独立 listing（无父无子，或父不在已知 SKU）
    for a in asins:
        if a not in asin2sku:
            continue
        if a in children_of or a in seen_child:
            continue
        groups.append({"parent_sku": asin2sku[a], "pt": sku2pt.get(asin2sku[a]),
                       "children": [], "standalone": True})
    return groups


# ---------- 5. 上传 ----------
def upload_group(g):
    parent_sku = g["parent_sku"]
    parent_ca = parent_sku + "-CA"
    pt = g["pt"]
    if g["standalone"]:
        # 独立 listing：单 SKU 可售，无变体
        attrs = bc.get_listing(parent_sku, auth.US)
        us_price = attrs["purchasable_offer"][0]["our_price"][0]["schedule"][0]["value_with_tax"]
        target, offer, listp = bc.calc_ca_price(us_price)
        patch = {"productType": pt, "requirements": "LISTING",
                 "attributes": bc.build(attrs, (target, offer, listp), parent_ca, False, pt,
                                        standalone=True)}
        st, r = bc.put_listing(parent_ca, patch)
        print(f"[独立] {parent_ca} -> {r.get('status')} (报价 {offer})")
        return parent_ca
    # 变体组：先父后子
    pattrs = bc.get_listing(parent_sku, auth.US)
    ppatch = {"productType": pt, "requirements": "LISTING",
              "attributes": bc.build(pattrs, None, parent_ca, True, pt)}
    st, r = bc.put_listing(parent_ca, ppatch)
    print(f"[父] {parent_ca} -> {r.get('status')}")
    time.sleep(2)
    for csku in g["children"]:
        csku_ca = csku + "-CA"
        cattrs = bc.get_listing(csku, auth.US)
        us_price = cattrs["purchasable_offer"][0]["our_price"][0]["schedule"][0]["value_with_tax"]
        target, offer, listp = bc.calc_ca_price(us_price)
        cpatch = {"productType": pt, "requirements": "LISTING",
                  "attributes": bc.build(cattrs, (target, offer, listp), csku_ca, False, pt, parent_ca)}
        st, r = bc.put_listing(csku_ca, cpatch)
        print(f"[子] {csku_ca} -> {r.get('status')} (报价 {offer})")
        time.sleep(2)
    return parent_ca


# ---------- 6. 回验 ----------
def verify(sku):
    qs = urllib.parse.urlencode({"marketplaceIds": auth.CA, "includedData": "summaries,issues",
                                 "issueLocale": "en_US"})
    try:
        st, r = auth.request("GET", f"/listings/2021-08-01/items/{auth.SELLER_ID}/{sku}?{qs}")
    except Exception:
        return None, "404", {}
    summ = (r.get("summaries") or [{}])[0]
    codes = {}
    for i in (r.get("issues") or []):
        if i.get("severity") == "ERROR":
            codes[i.get("code")] = codes.get(i.get("code"), 0) + 1
    return summ.get("asin"), summ.get("status"), codes


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    arg = sys.argv[1]
    if arg == "--today":
        asins = fetch_today_asins()
        print(f"自动抓取 US 站当天新上架 {len(asins)} 个 ASIN")
    else:
        asins = [a.strip() for a in arg.split(",") if a.strip()]
        print(f"输入 {len(asins)} 个 ASIN: {asins}")

    asin2sku, sku2pt = search_us_listings()
    print(f"US 站全量 listing 已加载：{len(asin2sku)} 个 ASIN")

    groups = resolve_groups(asins, asin2sku, sku2pt)
    print(f"\n解析出 {len(groups)} 个组：")
    for g in groups:
        kind = "独立" if g["standalone"] else "变体"
        print(f"  [{kind}] {g['pt']}: 父 {g['parent_sku']} -> {len(g['children'])} 子 {g['children']}")

    print("\n开始上传...")
    all_ca_skus = []
    for g in groups:
        try:
            ca_sku = upload_group(g)
            all_ca_skus.append(ca_sku)
            if not g["standalone"]:
                all_ca_skus += [c + "-CA" for c in g["children"]]
        except Exception as e:
            print(f"  ⚠️ 组 {g['parent_sku']} 上传异常: {e}")

    print(f"\n等待 90s 异步校验...")
    time.sleep(90)

    print("\n===== 回验 =====")
    print(f"{'SKU':<28} {'ASIN':<12} {'状态':<16} 错误码")
    for sku in all_ca_skus:
        asin, status, codes = verify(sku)
        st = ",".join(status) if isinstance(status, list) else str(status)
        print(f"{sku:<28} {str(asin):<12} {st:<16} {codes}")


if __name__ == "__main__":
    main()
