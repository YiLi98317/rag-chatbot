"""确定性工具：回收价查询、租机费用计算、库存查询。

纯函数，金额公式原样保留，不让 LLM 算数字。
"""

from __future__ import annotations

import re
from typing import Dict, List

from chatbot.masanduo.data import load_buyback_prices, load_inventory, load_platform_rules


def query_buyback(model: str) -> str:
    """查询靓机汇回收价。参数 model 如 "14"、"16 Pro Max"。"""
    if not model:
        return "老板，请告诉我具体型号哈，比如'14'、'16 Pro Max'"

    model = model.strip()
    mk = model.lower().replace("iphone", "").replace("苹果", "").strip()

    data = load_buyback_prices()
    if not data:
        return "老板，回收价数据暂时加载不了，稍等我修一下～"

    prices = data.get("prices", [])

    conditions: List[str] = []
    for p in prices:
        for k in p:
            if k not in ("model", "capacity", "network") and k not in conditions:
                conditions.append(k)

    matched: List[Dict] = []
    for p in prices:
        if p["model"].lower() == mk:
            matched.append(p)
    if not matched:
        for p in prices:
            pm = p["model"].lower()
            if pm.startswith(mk) or mk.startswith(pm):
                matched.append(p)

    if not matched:
        models = sorted(set(p["model"] for p in prices))
        return (
            f"老板，靓机汇暂时没有 {model} 的回收价哦。目前有这些型号：{'、'.join(models)}。"
            "告诉我具体型号和容量我帮你查哈～"
        )

    display_model = matched[0]["model"]
    header = "| 容量 | " + " | ".join(conditions) + " |"
    sep = "|------|" + "|".join(["------"] * len(conditions)) + "|"
    rows = []
    for item in matched:
        cap = item["capacity"]
        vals = [str(item.get(cond, "-")) for cond in conditions]
        rows.append(f"| {cap} | " + " | ".join(vals) + " |")

    table = header + "\n" + sep + "\n" + "\n".join(rows)
    return f"老板，{display_model} 靓机汇回收报价（过保机型）：\n\n{table}"


def calculate_rental(sale_price: int, tier: str, periods: int, source: str = "app") -> str:
    """计算租机费用。

    sale_price 售价(元)；tier 折扣如 "5折"（仅 2~6 折）；periods 期数 6 或 12；
    source "app" 或 "pc"（PC 端含会员服务费）。
    """
    if periods not in [6, 12]:
        return "老板，期数只有6期和12期两种哦～"

    rules = load_platform_rules()
    tiers_data: Dict[str, Dict] = {}
    tiers_key = "pc_tiers" if source == "pc" else "app_tiers"
    for t in rules.get(tiers_key, {}).get("tiers", []):
        tiers_data[t["name"]] = t

    tier_num_match = re.search(r"(\d+)", tier)
    tier_info = None
    if tier_num_match:
        tier_num = int(tier_num_match.group(1))
        if tier_num < 2 or tier_num > 6:
            return f"老板，平台只有 2折、3折、4折、5折、6折 这五个档位哦～你问的{tier}不在范围内。"
        for candidate in [tier, f"{tier_num}折", f"{tier_num}折购机"]:
            if candidate in tiers_data:
                tier_info = tiers_data[candidate]
                break

    if not tier_info:
        available = "、".join(tiers_data.keys())
        return f"老板，没找到{tier}这个档位哦。目前可选档位：{available}。比如'5折'、'4折'这样～"

    if source == "pc":
        period_key = f"period_{periods}"
        period_data = tier_info.get(period_key, {})
        rate_str = period_data.get("pc_fee", "12%")
        member_fee_str = period_data.get("member_fee", "无")
        reward_str = period_data.get("merchant_reward", "无")
        rate = float(rate_str.replace("%", "")) / 100
        service_fee = int(sale_price * rate)
        member_fee = 0
        if member_fee_str != "无":
            member_rate = float(member_fee_str.replace("%", "")) / 100
            member_fee = int(sale_price * member_rate)
        tier_num = int(re.search(r"(\d+)", tier_info["name"]).group(1))
        min_down_rate = tier_num / 10
        min_down = int(sale_price * min_down_rate)
        total_price = sale_price + service_fee + 50
        divisor = 5 if periods == 6 else 11
        monthly = int((total_price - min_down) / divisor)

        lines = [
            f"老板，帮您算好啦（{tier_info['name']}，PC端{periods}期）：",
            f"  售价：{sale_price}元",
            f"  服务费：{service_fee}元（费率{rate_str}）",
        ]
        if member_fee > 0:
            lines.append(f"  会员服务费：{member_fee}元（{member_fee_str}，客户在平台支付）")
        lines.extend(
            [
                f"  设备管理费：50元",
                f"  订单总价：{total_price}元",
                f"  最低首付：{min_down}元（{tier_info['name']}档）",
                f"  月供：{monthly}元（共还{divisor}个月）",
            ]
        )
        if reward_str != "无":
            reward = int(sale_price * float(reward_str.replace("%", "")) / 100)
            lines.append(f"  商家返点：{reward}元（{reward_str}）")
        return "\n".join(lines)

    rate_key = f"rate_{periods}"
    rate_str = tier_info.get(rate_key, "12%")
    min_down_str = tier_info.get("min_down", "40%起")
    rate = float(rate_str.replace("%", "")) / 100
    try:
        min_down_rate = float(min_down_str.replace("%起", "").replace("%", "")) / 100
    except Exception:
        min_down_rate = 0.4

    service_fee = int(sale_price * rate)
    total_price = sale_price + service_fee + 50
    min_down = int(sale_price * min_down_rate)
    divisor = 5 if periods == 6 else 11
    monthly = int((total_price - min_down) / divisor)

    lines = [
        f"老板，帮您算好啦（{tier_info.get('name', tier)}，{periods}期）：",
        f"  售价：{sale_price}元",
        f"  服务费：{service_fee}元（费率{rate_str}）",
        f"  设备管理费：50元",
        f"  订单总价：{total_price}元",
        f"  最低首付：{min_down}元",
        f"  月供：{monthly}元（共还{divisor}个月）",
    ]
    return "\n".join(lines)


def query_inventory_agent(model: str = "") -> str:
    """查询本店库存。model 可选。"""
    inventory = load_inventory()

    if model:
        model_lower = model.lower().replace("iphone ", "").strip()
        items = [i for i in inventory if model_lower in i["model"].lower().replace("iphone ", "")]
    else:
        items = inventory

    if not items:
        return f"老板，没有找到 {model} 的库存哦，可能是还没录入～"

    total = sum(i["stock"] for i in items)
    lines = ["老板，当前库存如下："]
    for i in items:
        price_str = "未定价" if not i["price"] else f"{i['price']}元"
        lines.append(f"  {i['model']} {i['color']} {i['condition']} {price_str} 库存{i['stock']}台")
    lines.append(f"合计：{total}台")
    return "\n".join(lines)
