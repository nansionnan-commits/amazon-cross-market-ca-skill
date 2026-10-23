# -*- coding: utf-8 -*-
"""批量：把今日 US 新上架的变体组复制到 CA 站（先父后子）。

- 自动读取每个 ASIN 的 PT 及其 CA schema 必填字段，做校验。
- 价格：target = US our_price + 5.99；CA 报价 = target×1.38−9.99 四舍五入 .99；list_price = 报价×1.7。
- 品牌 Generic；变体 COLOR；库存 500；处理 2 天；manufacturer_contact_information 必填。
"""
import json
import time
import urllib.parse
from datetime import datetime, timezone

import auth

US_FREIGHT = 5.99
CA_FREIGHT = 9.99
CA_RATE = 1.38

# 已确认 CA 站不适用的字段（报 WARNING，直接去掉）
DROP_KEYS = {
    "purchasable_offer", "list_price", "fulfillment_availability",
    "skip_offer", "condition_type", "merchant_shipping_group",
    "parentage_level", "child_parent_sku_relationship",
    "main_offer_image_locator", "other_offer_image_locator_1",
    "other_offer_image_locator_2", "other_offer_image_locator_3",
    "other_offer_image_locator_4", "other_offer_image_locator_5",
    "product_site_launch_date", "title_differentiation",
    "import_designation", "item_type_keyword",
}

# 各 PT 的条件必填补充字段
PT_EXTRA = {
    "PET_APPAREL": {"warranty_description": "No warranty"},
    "DESK_PAD": {"warranty_description": "No warranty"},
    "ANIMAL_SHELTER": {"warranty_description": "No warranty"},
    "ADVENT_CALENDAR": {"recommended_browse_nodes": "37309966011"},
}


def get_listing(sku, marketplace):
    qs = urllib.parse.urlencode({"marketplaceIds": marketplace, "includedData": "attributes"})
    st, r = auth.request("GET", f"/listings/2021-08-01/items/{auth.SELLER_ID}/{sku}?{qs}")
    return r.get("attributes") or {}


def put_listing(sku, patch):
    qs = urllib.parse.urlencode({"marketplaceIds": auth.CA})
    return auth.request("PUT", f"/listings/2021-08-01/items/{auth.SELLER_ID}/{sku}?{qs}", patch)


def round_to_99(x):
    return round(int(x + 0.5) - 0.01 + 0.0, 2)


def calc_ca_price(us_our_price):
    target = us_our_price + US_FREIGHT
    offer = round_to_99(target * CA_RATE - CA_FREIGHT)
    listp = round(offer * 1.7, 2)
    return target, offer, listp


def retag(value, marketplace=auth.CA, language="en_CA"):
    if isinstance(value, list):
        return [retag(v, marketplace, language) for v in value]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k == "marketplace_id":
                out[k] = marketplace
            elif k == "language_tag":
                out[k] = language
            else:
                out[k] = retag(v, marketplace, language)
        return out
    return value


def build(attrs, us_price, sku_ca, is_parent, pt, parent_sku_ca=None, standalone=False):
    a = {k: retag(v) for k, v in attrs.items() if k not in DROP_KEYS}
    a["brand"] = [{"value": "Generic", "language_tag": "en_CA", "marketplace_id": auth.CA}]
    # manufacturer：Generic 品牌下，manufacturer 为空则补 Generic（部分 PT 必填，US 站可能没填）
    mfr = a.get("manufacturer")
    if not mfr or not any(x.get("value") for x in mfr if isinstance(x, dict)):
        a["manufacturer"] = [{"value": "Generic", "language_tag": "en_CA", "marketplace_id": auth.CA}]
    name = (attrs.get("item_name") or [{}])[0].get("value", "")
    name = name.replace("EAOEIHD ", "").replace("EAOEIHD", "").strip()
    a["item_name"] = [{"value": name, "language_tag": "en_CA", "marketplace_id": auth.CA}]
    a["country_of_origin"] = [{"value": "CN", "marketplace_id": auth.CA}]
    a["supplier_declared_has_product_identifier_exemption"] = [{"value": True, "marketplace_id": auth.CA}]
    a["batteries_required"] = [{"value": False, "marketplace_id": auth.CA}]
    a["manufacturer_contact_information"] = [{"value": "15687345 " + datetime.now(timezone.utc).strftime("%Y%m%d"), "language_tag": "en_CA", "marketplace_id": auth.CA}]
    a["model_name"] = [{"value": sku_ca, "marketplace_id": auth.CA}]
    a["model_number"] = [{"value": sku_ca, "marketplace_id": auth.CA}]
    if standalone:
        # 独立 listing：可售、无变体关系（不填 parentage_level / variation_theme / child_parent_sku_relationship）
        a.pop("variation_theme", None)
        a.pop("parentage_level", None)
        a.pop("child_parent_sku_relationship", None)
        a["purchasable_offer"] = [{
            "currency": "CAD", "audience": "ALL",
            "our_price": [{"schedule": [{"value_with_tax": us_price[1]}]}],
            "quantity": 500, "marketplace_id": auth.CA,
        }]
        a["list_price"] = [{"currency": "CAD", "value": us_price[2], "marketplace_id": auth.CA}]
        a["fulfillment_availability"] = [{
            "fulfillment_channel_code": "DEFAULT", "quantity": 500,
            "lead_time_to_ship_max_days": 2, "marketplace_id": auth.CA,
        }]
    else:
        a["variation_theme"] = [{"name": "COLOR"}]
        if is_parent:
            a.pop("color", None)
            a["parentage_level"] = [{"value": "parent", "marketplace_id": auth.CA}]
            a["child_parent_sku_relationship"] = [{"child_relationship_type": "variation", "marketplace_id": auth.CA}]
        else:
            a["purchasable_offer"] = [{
                "currency": "CAD", "audience": "ALL",
                "our_price": [{"schedule": [{"value_with_tax": us_price[1]}]}],
                "quantity": 500, "marketplace_id": auth.CA,
            }]
            a["list_price"] = [{"currency": "CAD", "value": us_price[2], "marketplace_id": auth.CA}]
            a["fulfillment_availability"] = [{
                "fulfillment_channel_code": "DEFAULT", "quantity": 500,
                "lead_time_to_ship_max_days": 2, "marketplace_id": auth.CA,
            }]
            a["parentage_level"] = [{"value": "child", "marketplace_id": auth.CA}]
            a["child_parent_sku_relationship"] = [{
                "child_relationship_type": "variation", "parent_sku": parent_sku_ca,
                "marketplace_id": auth.CA,
            }]
    # unit_count.type.value 枚举大小写修正：US 站是大写 "Count"，CA 站枚举要求小写 "count"（PET_APPAREL/DISHWARE_BOWL/ANIMAL_SHELTER 等均敏感，统一转小写）
    if "unit_count" in a:
        for uc in a["unit_count"]:
            t = uc.get("type")
            if isinstance(t, dict) and isinstance(t.get("value"), str):
                t["value"] = t["value"].lower()
    # ADVENT_CALENDAR 的 format 修正：US 站是 advent_calendar，CA 站目录匹配需 box_calendar（参考成功 listing 1X-XZ00-84PH）
    if pt == "ADVENT_CALENDAR" and "format" in a:
        a["format"] = [{"value": "box_calendar", "marketplace_id": auth.CA}]
    extra = PT_EXTRA.get(pt, {})
    if "warranty_description" in extra:
        a["warranty_description"] = [{"value": extra["warranty_description"], "language_tag": "en_CA", "marketplace_id": auth.CA}]
    if "recommended_browse_nodes" in extra:
        a["recommended_browse_nodes"] = [{"value": extra["recommended_browse_nodes"], "marketplace_id": auth.CA}]
    return a


def main():
    groups = json.load(open("ca_groups.json", encoding="utf-8"))
    results = []
    for g in groups:
        parent_sku = g["parent_sku"]
        parent_sku_ca = parent_sku + "-CA"
        children = g["children"]
        # 父
        pattrs = get_listing(parent_sku, auth.US)
        ppatch = {"productType": g["pt"], "requirements": "LISTING",
                  "attributes": build(pattrs, None, parent_sku_ca, True, g["pt"])}
        st, r = put_listing(parent_sku_ca, ppatch)
        results.append(("父", parent_sku_ca, r.get("status"), r.get("issues")))
        print(f"[父] {parent_sku_ca} -> {r.get('status')}")
        time.sleep(1)
        # 子
        for csku in children:
            csku_ca = csku + "-CA"
            cattrs = get_listing(csku, auth.US)
            us_price = cattrs["purchasable_offer"][0]["our_price"][0]["schedule"][0]["value_with_tax"]
            target, offer, listp = calc_ca_price(us_price)
            cpatch = {"productType": g["pt"], "requirements": "LISTING",
                      "attributes": build(cattrs, (target, offer, listp), csku_ca, False, g["pt"], parent_sku_ca)}
            st, r = put_listing(csku_ca, cpatch)
            results.append(("子", csku_ca, r.get("status"), f"报价={offer} list={listp}"))
            print(f"[子] {csku_ca} -> {r.get('status')} (报价{offer}/划线{listp})")
            time.sleep(1)
    json.dump(results, open("batch_results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("\n批量完成，结果已存 batch_results.json")


if __name__ == "__main__":
    main()
