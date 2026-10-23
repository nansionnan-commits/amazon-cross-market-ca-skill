---
name: amazon-cross-market-listing
description: 亚马逊跨站复制 Listing（US→CA）。当老板要"把 US 站 ASIN 复制到 CA 站 / 加拿大站上传 / 跨站复制 listing / US 转 CA / 传这几个 ASIN 到加拿大"时使用。给定 US ASIN 自动取产品类型、按 1.38 乘数换算价格、Generic 品牌 + GTIN 豁免 + COLOR 变体上传，并开完回验。
---

# 亚马逊跨站复制 Listing（US → CA）

把 US 站 ASIN 自动复制到 CA 站（加拿大站）上架。价格 = US 售价换算，品牌 Generic + GTIN 豁免，变体 COLOR 全复制，图片 CDN 透传。

## 触发条件

老板说「复制 listing 到 CA」「跨站上传」「US 转 CA」「传这几个 ASIN 到加拿大站」「把今天新上架传到 CA」等。

## 一键用法

```bash
cd sp-api
python run_all.py B0XXX,B0YYY,B0ZZZ     # 给定 US 站 ASIN（逗号分隔，可混父/子/独立）
python run_all.py --today               # 自动抓 US 站当天(UTC)新上架
```

## 完整流程

1. 反查 SKU + PT（`searchListingsItems` 翻页拿全量 `asin→sku`、`sku→productType` 映射）
2. 父子分组（`catalog/relationships` 判断父/子/独立）
3. 构建 CA patch（`batch_ca.build`，铁律全部固化在代码里）
4. 上传（变体组先父后子；独立 listing 单 SKU 可售）
5. 回验（等 90s，逐 SKU 查 ASIN / 状态 / 错误码）

## 铁律（血泪教训，务必照抄，不要改）

- **乘数 1.38**（2026-10-10 老板定版，之前 1.55 作废）；CA 运费 C$9.99；`list_price = 报价 × 1.7`；报价 = (US our_price + 5.99) × 1.38 − 9.99 四舍五入到 .99。
- **language_tag 必须 `en_CA`**（填 en_US 会全字段 100720 Invalid language data）。
- 品牌 `Generic`；变体主题 `COLOR`；库存 500；处理 2 天；`supplier_declared_has_product_identifier_exemption = true`。
- **开完必回验**：`DISCOVERABLE ≠ 有曝光`，上传后 24-48h 内回查真实状态，不能只看返回的 ACCEPTED。
- **issues 有「粘性」**：字段错一次，重传正确值旧 issues 不刷新 → 只能删除重建（DELETE 子→父→等 ≥90s→PUT 父→子），或用新 SKU 加 `-1` 后缀。
- **枚举值大小写/拼写跨站不一致**：`unit_count.type.value` US 大写 "Count"，CA 站 PET_APPAREL 只认小写 "count"（已固化在 build 里）。
- **降临日历类目（ADVENT_CALENDAR）**：可售 SKU 必须有真实 UPC/EAN，GTIN 豁免对该类目可售 SKU 不生效（只对不可售父体生效）；需老板后台申请「降临日历 + Generic」豁免，SP-API 无法代申请。
- 老店大部分类目老板已手动豁免过，可直接传，出问题看报错定位。

## 脚本

- `scripts/auth.py`：LWA 认证（凭证动态读取，不落盘 secret）
- `scripts/batch_ca.py`：构建 patch（含全部铁律 + PT_EXTRA 条件必填表）
- `scripts/run_all.py`：一键入口（反查→分组→上传→回验）

## 常见错误码速查

| 错误码 | 含义 | 处理 |
|---|---|---|
| 100720 | 语言标签错误（en_US 用在 CA） | language_tag 改 en_CA + 删除重建 |
| 8560 | 缺 UPC / 无法创建 ASIN | 降临日历类目 → 后台申请豁免或提供 UPC |
| 90253 | child 缺 parent_sku | 变体子体必须带 parent_sku |
| 8541 | 幽灵 ASIN 冲突 | 删除后等缓存失效，或新 SKU 加 -1 |
| 90244 | 枚举值错误 | 检查 unit_count 等枚举大小写 |
| 5995 | 品牌被锁不能改 | 别乱改 brand，需开 case 解锁 |
| 100588 | 主图非纯白底 | 无害，不抑制 ASIN，无需操作 |
| 100521 | 审核中 | 等 48h，非数据错误 |
