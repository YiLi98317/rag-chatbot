# -*- coding: utf-8 -*-
"""马三多工具函数 - 价格查询、费用计算、库存查询"""

import json
import os

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
KNOWLEDGE_DIR = os.path.join(os.path.dirname(TOOLS_DIR), "knowledge")

# 成色中文名映射
CONDITION_NAMES = {
    "靓机": "靓机（完美无瑕疵）",
    "小花": "小花（少量轻微划痕）",
    "大花": "大花（磕碰划痕较明显）",
    "外爆": "外爆（外框碎边，内屏完好）",
    "内爆可测": "内爆可测（内屏坏但可检测）",
}


def _load_buyback_prices():
    """从 JSON 文件加载完整回收价数据"""
    json_path = os.path.join(KNOWLEDGE_DIR, "buyback_prices.json")
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def query_buyback(model: str) -> str:
    """
    查询靓机汇回收价格。
    参数 model: 手机型号，如 "14"、"16 Pro Max"
    返回: 全部成色和容量的格式化价格文本
    """
    if not model:
        return "老板，请告诉我具体型号哈，比如'14'、'16 Pro Max'"

    model = model.strip()
    mk = model.lower().replace("iphone", "").replace("苹果", "").strip()

    data = _load_buyback_prices()
    if not data:
        return "老板，回收价数据暂时加载不了，稍等我修一下～"

    prices = data.get("prices", [])

    # 提取所有不重复的成色列（跳过 model / capacity / network）
    conditions = []
    for p in prices:
        for k in p:
            if k not in ("model", "capacity", "network") and k not in conditions:
                conditions.append(k)

    # 按 model 精确匹配，再模糊匹配
    matched = []
    for p in prices:
        pm = p["model"].lower()
        if pm == mk:
            matched.append(p)
    if not matched:
        for p in prices:
            pm = p["model"].lower()
            if pm == mk.replace("pro max", "pro max").replace("pro", "pro").strip():
                matched.append(p)
    if not matched:
        for p in prices:
            pm = p["model"].lower()
            if pm.startswith(mk) or mk.startswith(pm):
                matched.append(p)

    if not matched:
        # 列出可用型号
        models = sorted(set(p["model"] for p in prices))
        return f"老板，靓机汇暂时没有 {model} 的回收价哦。目前有这些型号：{'、'.join(models)}。告诉我具体型号和容量我帮你查哈～"

    # 如果匹配了多个型号（不同容量），按模型分组展示
    display_model = matched[0]["model"]
    
    # Markdown 表格格式（PC端渲染为可视化表格）
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
    """
    计算租机费用。
    参数:
      sale_price: 手机售价（元）
      tier: 折扣档位，如 "5折"、"4折"（注意：只有2折~6折，不支持8折等）
      periods: 期数，6或12
      source: "app"（APP端费率）或 "pc"（PC端费率，含会员服务费）
    返回: 费用明细文本
    """
    if periods not in [6, 12]:
        return "老板，期数只有6期和12期两种哦～"

    # 加载档位费率
    rules_path = os.path.join(KNOWLEDGE_DIR, "platform_rules.json")
    tiers_data = {}
    if os.path.exists(rules_path):
        with open(rules_path, "r", encoding="utf-8") as f:
            rules = json.load(f)
        # 根据来源选择费率表
        tiers_key = "pc_tiers" if source == "pc" else "app_tiers"
        for t in rules.get(tiers_key, {}).get("tiers", []):
            tiers_data[t["name"]] = t

    # 匹配档位：提取数字，优先精确匹配，再尝试从键名匹配
    import re
    tier_num_match = re.search(r'(\d+)', tier)
    tier_info = None
    if tier_num_match:
        tier_num = int(tier_num_match.group(1))
        # 档位必须是2~6折
        if tier_num < 2 or tier_num > 6:
            return f"老板，平台只有 2折、3折、4折、5折、6折 这五个档位哦～你问的{tier}不在范围内。"
        # 尝试多种匹配：精确匹配用户输入 -> "X折" -> "X折购机"
        for candidate in [tier, f"{tier_num}折", f"{tier_num}折购机"]:
            if candidate in tiers_data:
                tier_info = tiers_data[candidate]
                break

    if not tier_info:
        available = "、".join(tiers_data.keys())
        return f"老板，没找到{tier}这个档位哦。目前可选档位：{available}。比如'5折'、'4折'这样～"

    # 根据来源区分处理（APP端和PC端字段结构不同）
    if source == "pc":
        period_key = f"period_{periods}"
        period_data = tier_info.get(period_key, {})
        rate_str = period_data.get("pc_fee", "12%")
        member_fee_str = period_data.get("member_fee", "无")
        reward_str = period_data.get("merchant_reward", "无")
        # PC端费率
        rate = float(rate_str.replace("%", "")) / 100
        service_fee = int(sale_price * rate)
        # 会员服务费
        member_fee = 0
        if member_fee_str != "无":
            member_rate = float(member_fee_str.replace("%", "")) / 100
            member_fee = int(sale_price * member_rate)
        # 最低首付
        tier_num = int(re.search(r'(\d+)', tier_info["name"]).group(1))
        min_down_rate = tier_num / 10
        min_down = int(sale_price * min_down_rate)
        # 月供计算
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
        lines.extend([
            f"  设备管理费：50元",
            f"  订单总价：{total_price}元",
            f"  最低首付：{min_down}元（{tier_info['name']}档）",
            f"  月供：{monthly}元（共还{divisor}个月）",
        ])
        if reward_str != "无":
            reward = int(sale_price * float(reward_str.replace("%", "")) / 100)
            lines.append(f"  商家返点：{reward}元（{reward_str}）")
        return "\n".join(lines)
    else:
        # APP端原有逻辑
        rate_key = f"rate_{periods}"
        rate_str = tier_info.get(rate_key, "12%")
        min_down_str = tier_info.get("min_down", "40%起")
        rate = float(rate_str.replace("%", "")) / 100
        try:
            min_down_rate = float(min_down_str.replace("%起", "").replace("%", "")) / 100
        except:
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


_INVENTORY_PATH = os.path.join(os.path.dirname(__file__), "..", "knowledge", "inventory.json")

def _load_inventory():
    """加载库存数据，优先从 JSON 文件读，否则用默认数据"""
    if os.path.exists(_INVENTORY_PATH):
        try:
            with open(_INVENTORY_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    return data
        except:
            pass
    # 默认库存
    return [
        {"model": "iPhone 16 Pro Max", "color": "沙漠色", "price": 9999, "condition": "99新", "stock": 2},
        {"model": "iPhone 16 Pro Max", "color": "原色", "price": 9499, "condition": "95新", "stock": 1},
        {"model": "iPhone 16 Pro", "color": "沙漠色", "price": 7999, "condition": "99新", "stock": 2},
        {"model": "iPhone 16", "color": "群青色", "price": 5999, "condition": "99新", "stock": 3},
        {"model": "iPhone 15 Pro Max", "color": "原色钛金属", "price": 6800, "condition": "95新", "stock": 1},
        {"model": "iPhone 15 Pro", "color": "白色钛金属", "price": 5800, "condition": "95新", "stock": 3},
        {"model": "iPhone 15", "color": "粉色", "price": 4200, "condition": "95新", "stock": 2},
        {"model": "iPhone 14 Pro Max", "color": "深紫色", "price": 5200, "condition": "95新", "stock": 1},
        {"model": "iPhone 14", "color": "午夜色", "price": 3500, "condition": "95新", "stock": 3},
    ]

def query_inventory_agent(model: str = "") -> str:
    """
    查询本店库存。
    参数 model: 可选，手机型号
    """
    inventory = _load_inventory()

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


# 工具注册表（给 agent 用）
TOOLS = {
    "query_buyback": {
        "function": query_buyback,
        "description": "查询靓机汇回收价格。当老板问回收价、二手价、卖给靓机汇多少钱时必须调用。",
        "parameters": {"model": "手机型号，如 14、15 Pro、16 Pro Max"}
    },
    "calculate_rental": {
        "function": calculate_rental,
        "description": "计算租机费用。当老板给了售价+折扣+期数并要求算账时必须调用。",
        "parameters": {"sale_price": "售价(元)", "tier": "折扣如5折/4折（仅2~6折）", "periods": "期数6或12", "source": "app或pc（默认app）"}
    },
    "query_inventory": {
        "function": query_inventory_agent,
        "description": "查询本店库存和售价。当老板问库存、有货没、有什么机型时必须调用。",
        "parameters": {"model": "可选，手机型号，不传则查全部"}
    },
}


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python masanduo_tools.py <command> [args...]")
        print("  buyback <型号>        查回收价")
        print("  rental <售价> <折扣> <期数> [app|pc]  算费用")
        print("  inventory [型号]      查库存")
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "buyback":
        model = sys.argv[2] if len(sys.argv) > 2 else ""
        print(query_buyback(model))
    elif cmd == "rental":
        if len(sys.argv) < 5:
            print("用法: rental <售价> <折扣> <期数> [app|pc]")
        else:
            source = sys.argv[5] if len(sys.argv) > 5 else "app"
            print(calculate_rental(int(sys.argv[2]), sys.argv[3], int(sys.argv[4]), source))
    elif cmd == "inventory":
        model = sys.argv[2] if len(sys.argv) > 2 else ""
        print(query_inventory_agent(model))
    else:
        print(f"未知命令: {cmd}")
