"""业务计算层：意图 → 纯结构化数据（不调 LLM）。

只移植 server.py 的"活路径"，丢弃死代码（_composite_chain / _deepseek_with_data /
未用的 INTENT_CLASSIFY_PROMPT），并补全 sales_tips 分支。
"""

from __future__ import annotations

import json
import random
import re
from typing import Any, Dict, List

from chatbot.masanduo.data import load_buyback_prices, load_phone_specs, load_platform_rules
from chatbot.masanduo.extract import ALIAS_MAP, extract_model
from chatbot.masanduo.session import get_state, update_state
from chatbot.masanduo.tools import calculate_rental, query_buyback, query_inventory_agent


# ====== 顶层入口 ======

def compute(msg: str, session_id: str, intent: str, model: str) -> Dict[str, Any]:
    """输入：用户消息 + 路由意图 → 输出：{"intent","data"} 或 {"error"}。"""
    state = get_state(session_id)
    try:
        if intent == "buyback":
            m = model or state.get("old_device", "")
            data = {"model": m, "result": query_buyback(m) if m else ""}
            update_state(session_id, old_device=m or model, last_intent="buyback")
            return {"intent": "buyback", "data": data}

        if intent == "inventory":
            data = {"model": model, "result": query_inventory_agent(model or "")}
            update_state(session_id, last_intent="inventory")
            return {"intent": "inventory", "data": data}

        if intent == "rental":
            data = {"result": _smart_rental(msg)}
            update_state(session_id, last_intent="rental")
            return {"intent": "rental", "data": data}

        if intent == "composite":
            data = _compute_composite(msg, session_id, state)
            update_state(session_id, last_intent="composite")
            return {"intent": "composite", "data": data}

        if intent == "pricing":
            m = model or state.get("old_device", "")
            data = {"model": m, "result": _pricing_analysis(msg, m or "")}
            update_state(session_id, last_intent="pricing")
            return {"intent": "pricing", "data": data}

        if intent == "rules":
            data = {"result": _query_rules(msg)}
            update_state(session_id, last_intent="rules")
            return {"intent": "rules", "data": data}

        if intent == "specs":
            data = _compute_specs(msg, model, state)
            update_state(session_id, last_intent="specs")
            return {"intent": "specs", "data": data}

        if intent == "lock":
            data = {"result": _query_lock(msg)}
            update_state(session_id, last_intent="lock")
            return {"intent": "lock", "data": data}

        if intent == "store_overview":
            data = {"result": _query_store_overview()}
            update_state(session_id, last_intent="store_overview")
            return {"intent": "store_overview", "data": data}

        if intent == "biz_knowledge":
            data = {"result": _query_biz_knowledge(msg)}
            update_state(session_id, last_intent="biz_knowledge")
            return {"intent": "biz_knowledge", "data": data}

        if intent == "sales_tips":
            data = {"result": _query_sales_tips()}
            update_state(session_id, last_intent="sales_tips")
            return {"intent": "sales_tips", "data": data}
    except Exception as e:  # noqa: BLE001
        return {"error": f"老板，{intent} 查的时候出了点问题：{e}"}

    update_state(session_id, last_intent="chat")
    return {"intent": "chat", "data": {}}


# ====== 复合推演 ======

_CN_NUM_MAP = {
    "三千": 3000, "四千": 4000, "五千": 5000, "六千": 6000, "七千": 7000,
    "八千": 8000, "九千": 9000, "一万": 10000, "两万": 20000, "三万": 30000,
    "四万": 40000, "五万": 50000, "一千": 1000, "两千": 2000, "八百": 800,
}


def _extract_models_ordered(msg: str) -> List[str]:
    """按出现顺序提取消息中的所有 iPhone 型号（含俗称与裸数字 8-17）。

    预算等大数字（如 2000、1500）不会被误判为型号：裸型号数字用单/双位
    边界 (?<!\\d)\\d{1,2}(?!\\d) 匹配，"2000" 不会切出 "20"。
    """
    s = msg.lower().replace(" ", "")
    found: List[tuple] = []
    spans: List[tuple] = []

    for alias in sorted(ALIAS_MAP.keys(), key=len, reverse=True):
        start = 0
        while True:
            i = s.find(alias, start)
            if i < 0:
                break
            found.append((i, ALIAS_MAP[alias]))
            spans.append((i, i + len(alias)))
            start = i + len(alias)

    for m in re.finditer(r"(?<!\d)\d{1,2}(?!\d)", s):
        n = int(m.group())
        if 8 <= n <= 17 and not any(a <= m.start() < b for a, b in spans):
            found.append((m.start(), str(n)))

    found.sort(key=lambda x: x[0])
    out: List[str] = []
    seen = set()
    for _, mod in found:
        if mod not in seen:
            out.append(mod)
            seen.add(mod)
    return out


def _compute_composite(msg: str, session_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
    msg_lower = msg.lower()
    is_rental = any(kw in msg_lower for kw in ["租机", "分期", "折", "走平台", "租", "办单"])
    is_full = any(
        kw in msg_lower for kw in ["全款", "全价", "一次性", "一口价", "直接买", "不租", "买断"]
    ) or not is_rental
    has_trade = any(
        kw in msg_lower
        for kw in ["换", "置换", "抵", "旧机", "以旧换新", "手上有", "手里有", "有一台", "有台", "有部", "有个"]
    )

    models = _extract_models_ordered(msg)
    target_model = ""
    old_model = ""
    if len(models) >= 2:
        old_model, target_model = models[0], models[1]
    elif len(models) == 1 and has_trade:
        old_model = models[0]
    elif len(models) == 1:
        target_model = models[0]
    elif has_trade:
        old_model = state.get("old_device", "")

    cash = 0
    for cn, v in _CN_NUM_MAP.items():
        if cn in msg:
            cash = v
            break
    if cash == 0:
        for n in re.findall(r"(?<!\d)(\d{3,5})(?!\d)", msg):
            iv = int(n)
            if 500 <= iv <= 50000:
                cash = iv
                break

    buyback_result = ""
    buyback_value = 0
    if old_model:
        buyback_result = query_buyback(old_model)
        prices_data = load_buyback_prices()
        if prices_data:
            mk = old_model.lower().replace("iphone ", "").replace("iphone", "").strip()
            for p in prices_data.get("prices", []):
                if p["model"].lower().strip() == mk and "靓机" in p:
                    buyback_value = int(p.get("靓机", 0))
                    break

    inventory_result = query_inventory_agent(target_model or "")
    total = buyback_value + cash
    update_state(session_id, budget=cash, target=target_model, old_device=old_model)

    return {
        "mode": "full" if is_full else "rental",
        "old_model": old_model,
        "target_model": target_model,
        "buyback_value": buyback_value,
        "buyback_result": buyback_result,
        "cash": cash,
        "total": total,
        "inventory": inventory_result,
        "has_old_device": bool(old_model),
    }


# ====== 参数（支持多型号对比） ======

def _compute_specs(msg: str, model: str, state: Dict[str, Any]) -> Dict[str, Any]:
    models_raw = re.findall(r"iphone\s*(\d{1,2}\s*(?:pro\s*max|pm|pro|plus|mini)?)", msg, re.IGNORECASE)
    models: List[str] = []
    seen = set()
    for m in models_raw:
        std = extract_model(m)
        if std and std not in seen:
            models.append(std)
            seen.add(std)
    if not models:
        models = [model or state.get("old_device", "")]

    if len(models) >= 2:
        results = [{"model": m, "specs": _query_specs(m)} for m in models]
        return {"models": results, "compare": True}
    return {"model": models[0] if models else "", "result": _query_specs(models[0] if models else "")}


# ====== 智能租机 ======

def _smart_rental(msg: str) -> str:
    nums = re.findall(r"(\d+)", msg)
    price = None
    tier = None
    periods = None
    for n in nums:
        v = int(n)
        if v >= 1000 and price is None:
            price = v
        elif v in [2, 3, 4, 5, 6] and tier is None:
            tier = f"{v}折"
        elif v in [6, 12] and periods is None:
            periods = v

    if price and tier and periods:
        src = "pc" if "pc" in msg.lower() else "app"
        return calculate_rental(price, tier, periods, src)

    if price:
        missing = []
        if not tier:
            missing.append("打几折（2折~6折）")
        if not periods:
            missing.append("分多少期（6期/12期）")
        return (
            f"好嘞老板！售价 {price} 元记下了，还需要告诉我：{'、'.join(missing)}～"
            f"比如「{price}元的手机 5折 12期」我秒算"
        )

    tier_keywords = ["租机模式", "档位", "费率", "有什么", "怎么算"]
    if any(kw in msg.lower() for kw in tier_keywords):
        return _build_tier_table_full()

    guides = [
        "好嘞老板！要算租机费用得告诉我三样：手机售价、打几折、分多少期。比如「5000元的手机 5折12期」我秒算",
        "老板，算租机费用需要：手机售价、打几折、分多少期。或者直接说「5000 5折 12期」也行～",
    ]
    return random.choice(guides)


# ====== 定价分析 ======

def _pricing_analysis(msg: str, model: str) -> str:
    try:
        model_int = int(model) if model and model.strip().isdigit() else 0
    except ValueError:
        model_int = 0

    cost = None
    for n in re.findall(r"(\d+)", msg):
        v = int(n)
        if 500 <= v <= 5000 and cost is None and v != model_int:
            cost = v
            break

    buyback_data = query_buyback(model) if model else ""
    if not model and not cost:
        return "老板，告诉我是哪款手机、回收成本多少，我帮你算加多少钱卖～比如「iPhone12 回收900 义乌零售」"

    inventory_data = query_inventory_agent(model or "")

    msg_lower = msg.lower()
    city = ""
    for c in ["义乌", "杭州", "深圳", "北京", "上海", "广州", "成都"]:
        if c in msg_lower:
            city = c
            break

    channel = "零售"
    if "租机" in msg_lower or "分期" in msg_lower:
        channel = "租机"
    if "零售" in msg_lower:
        channel = "零售"

    lines = ["## 定价分析请求"]
    lines.append(f"- 型号：{model or '未知'}")
    lines.append(f"- 城市：{city or '未知'}")
    lines.append(f"- 渠道：{channel}")
    if cost:
        lines.append(f"- 回收成本：{cost}元")
    lines.append("")
    lines.append("## 回收价数据")
    lines.append(buyback_data if buyback_data else "无回收价数据")
    lines.append("")
    lines.append("## 库存参考")
    lines.append(inventory_data if inventory_data else "无库存数据")
    lines.append("")
    lines.append("## 定价建议模板")
    lines.append("1. 确认回收成本")
    lines.append("2. 定价表格：| 配置 | 回收价 | 建议零售价 | 毛利 | 利润率 |")
    lines.append("3. 城市特点一句话")
    lines.append("4. 零售vs租机对比")
    lines.append("5. 具体建议")
    lines.append("")
    lines.append("定价逻辑：二手零售加价20%~40%，义乌/走量城市偏低，一线城市偏高。租机可以标高售价。")
    return "\n".join(lines)


# ====== 档位费率表 ======

def _build_tier_table_full() -> str:
    rules = load_platform_rules()
    if not rules:
        return "老板，规则文件找不到了～"

    lines = ["## 租机档位"]

    def _build(tiers: List[Dict], title: str) -> List[str]:
        rows = [f"### {title}", "| 档位 | 6期费率 | 12期费率 | 服务内容 |", "|------|---------|----------|----------|"]
        for t in tiers:
            name = t.get("name", "")
            fee6 = t.get("rate_6", t.get("period_6", {}).get("pc_fee", t.get("period_6", {}).get("app_fee", "")))
            fee12 = t.get("rate_12", t.get("period_12", {}).get("pc_fee", t.get("period_12", {}).get("app_fee", "")))
            svc = t.get("service", t.get("period_6", {}).get("service", ""))
            rows.append(f"| {name} | {fee6} | {fee12} | {svc} |")
        return rows

    if "pc_tiers" in rules:
        lines.extend(_build(rules["pc_tiers"]["tiers"], "PC端"))
        lines.append("")
    if "app_tiers" in rules:
        lines.extend(_build(rules["app_tiers"]["tiers"], "APP端"))
        lines.append("")

    lines.append("## 计算公式")
    lines.append("- 服务费 = 手机售价 × 对应费率")
    lines.append("- 订单总价 = 售价 + 服务费 + 50元设备管理费")
    lines.append("- 最低首付 = 售价 × 对应首付比例")
    lines.append("- 6期月供 = (总价 − 首付) ÷ 5")
    lines.append("- 12期月供 = (总价 − 首付) ÷ 11")
    lines.append("")
    lines.append("## 核心规律")
    lines.append("- 首付比例越高 → 服务费率越低 → 总花费越少")
    lines.append("- 期数越长 → 月还款压力越小")
    lines.append("- 每单固定收50元设备管理费")

    if "settlement_rules" in rules:
        lines.append("")
        lines.append("## 首付直接门店收")
        for r in rules["settlement_rules"].get("rules", []):
            lines.append(f"- {r}")
    return "\n".join(lines)


# ====== 销售策略 ======

def _query_sales_tips() -> str:
    rules = load_platform_rules()
    tips = rules.get("sales_tips", {})
    if not tips:
        return "老板，销售策略模块还没配置好，稍等～"

    lines = [tips.get("description", "## 租机销售策略"), ""]

    push = tips.get("push_tiers", [])
    if push:
        lines.append("## 主推低首付档位")
        lines.append("| 档位 | 首付 | 卖点话术 |")
        lines.append("|------|------|----------|")
        for p in push:
            lines.append(f"| {p['tier']} | {p['down']} | \"{p['script']}\" |")
        lines.append("**客户心理：首付越低越容易冲动下单。推2折、3折最吸引人。**")
        lines.append("")

    scene = tips.get("scenario_targeting", [])
    if scene:
        lines.append("## 精准场景营销")
        lines.append("| 客户类型 | 推期数 | 理由 |")
        lines.append("|----------|--------|------|")
        for s in scene:
            lines.append(f"| {s['customer']} | {s['periods']} | {s['reason']} |")
        lines.append("")

    scripts = tips.get("sales_scripts", [])
    if scripts:
        lines.append("## 话术转化技巧")
        for s in scripts:
            lines.append(f"- **{s['trigger']}**：\"{s['response']}\"")
        lines.append("")

    ret = tips.get("retention_tips", [])
    if ret:
        lines.append("## 老客户复购")
        for r in ret:
            lines.append(f"- {r}")
        lines.append("")

    pc = tips.get("pc_reward", "")
    if pc:
        lines.append(f"## PC端返点\n{pc}\n")

    comp = tips.get("compliance", "")
    if comp:
        lines.append(f"## 合规底线\n{comp}\n")

    summary = tips.get("summary", "")
    if summary:
        lines.append(f"**{summary}**")
    return "\n".join(lines)


# ====== 门店概况 ======

def _query_store_overview() -> str:
    rules = load_platform_rules()
    store = rules.get("store_overview", {})
    if not store:
        return "老板，门店概况模块还没配置好～"

    lines = ["## 手机妈妈入驻门店概况\n"]
    lines.append(f"平台入驻门店总数：{store.get('total', '')}\n")
    types = store.get("types", [])
    if types:
        lines.append("### 四类门店\n")
        lines.append("| 门店类型 | 核心定位 | 规模特征 | 业务侧重 |")
        lines.append("|----------|----------|----------|----------|")
        for t in types:
            lines.append(f"| {t['name']} | {t['positioning']} | {t['scale']} | {t['focus']} |")
    common = store.get("common_biz", [])
    if common:
        lines.append(f"\n### 共性业务（四类门店均涉及）\n{'、'.join(common)}\n")
    biz = store.get("biz_detail", {})
    if biz:
        lines.append("### 回收业务\n")
        buyback = biz.get("buyback", {})
        lines.append(f"流通闭环：{buyback.get('cycle', '')}\n")
        rental = biz.get("rental", {})
        if rental:
            lines.append(f"### 租赁业务\n{rental.get('description', '')}\n")
        sales = biz.get("sales_scenarios", {})
        if sales:
            lines.append("### 销售场景\n")
            lines.append(f"- 全款购机：{sales.get('full_purchase', '')}")
            lines.append(f"- 旧机置换：{sales.get('trade_in', '')}")
            lines.append(f"- 以租代购：{sales.get('rent_to_own', '')}")
    return "\n".join(lines)


# ====== 经营知识 ======

def _query_biz_knowledge(msg: str) -> str:
    rules = load_platform_rules()
    biz = rules.get("biz_knowledge", {})
    if not biz:
        return "老板，经营知识模块还没配置好～"

    msg_lower = msg.lower()
    lines = ["## 手机门店经营知识\n"]
    matched: List[str] = []

    if any(kw in msg_lower for kw in ["员工", "团队", "薪酬", "招聘", "管理", "人员"]):
        s = biz.get("staff_management", {})
        lines.append(f"### 人员管理\n{s.get('summary', '')}")
        for r in s.get("rules", []):
            lines.append(f"- {r}")
        matched.append("staff")

    if any(kw in msg_lower for kw in ["引流", "抖音", "美团", "小红书", "大众点评", "闪购", "o2o", "线上", "渠道", "推广"]):
        s = biz.get("sales_channels", {})
        lines.append(f"\n### 引流与线上渠道\n{s.get('summary', '')}")
        lines.append(f"\n{s.get('o2o_intro', '')}")
        lines.append("\n各平台用法：")
        for p in s.get("platforms", []):
            lines.append(f"- **{p['name']}**：{p['use']}")
        for t in s.get("tips", []):
            lines.append(f"- {t}")
        matched.append("channel")

    if any(kw in msg_lower for kw in ["老客户", "留住", "流失", "截胡", "微信", "社群", "会员"]):
        s = biz.get("customer_retention", {})
        lines.append(f"\n### 客户留存\n{s.get('summary', '')}")
        for r in s.get("methods", []):
            lines.append(f"- {r}")
        matched.append("retention")

    if any(kw in msg_lower for kw in ["趋势", "出路", "行业", "不行了", "越来越难", "变革", "破局", "转型"]):
        s = biz.get("industry_trend", {})
        lines.append(f"\n### 行业趋势与出路\n{s.get('summary', '')}")
        for r in s.get("key_points", []):
            lines.append(f"- {r}")
        matched.append("trend")

    if any(kw in msg_lower for kw in ["进货", "渠道", "定价", "产品", "选品", "货源"]):
        s = biz.get("product_strategy", {})
        lines.append(f"\n### 产品与定价\n{s.get('summary', '')}")
        for r in s.get("tips", []):
            lines.append(f"- {r}")
        matched.append("product")

    if not matched:
        for section in ["sales_channels", "customer_retention", "staff_management", "product_strategy"]:
            s = biz.get(section, {})
            if not s:
                continue
            lines.append(f"\n### {s.get('summary', '')}")
            for r in s.get("rules", s.get("platforms", s.get("methods", s.get("tips", [])))):
                if isinstance(r, str):
                    lines.append(f"- {r}")
                elif isinstance(r, dict):
                    lines.append(f"- **{r.get('name', '')}**：{r.get('use', '')}")

    lines.append("\n### 手机妈妈工具结合")
    lines.append("老板可以把这些经营方法跟手机妈妈平台结合：")
    lines.append("- 租机模式本身就是引流利器：打出'月供XX元换新机'的噱头，抖音/小红书爆款素材")
    lines.append("- 以旧换新锁客：客户旧机只能抵给你，下次换机还找你")
    lines.append("- PC端检测软件：给客户看专业检测报告，建立信任感")
    lines.append("- 回收+租机组合：帮客户算'旧机抵首付，月供才XX'，转化率翻倍")
    return "\n".join(lines)


# ====== 锁机 ======

def _query_lock(msg: str) -> str:
    rules = load_platform_rules()
    lock = rules.get("lock_process", {})
    if not lock:
        return "老板，锁机知识模块还没配置好，稍等～"

    if any(w in msg for w in ["失败", "报错", "不行", "不成功", "无效", "问题", "排查"]):
        specific = lock.get("troubleshooting_specific", [])
        matched = None
        for sp in specific:
            problem = sp.get("problem", "")
            if any(kw in msg for kw in ["无锁头", "没有锁", "没锁"]) and "无锁头" in problem:
                matched = sp
                break
            if any(kw in msg for kw in ["自动设备注册", "分配给Apple商务管理", "配置其注册设置"]) and "自动设备注册" in problem:
                matched = sp
                break
            if any(kw in msg for kw in ["证书无效", "证书"]) and "证书无效" in problem:
                matched = sp
                break

        if matched:
            lines = [f"【锁机报错】{matched['problem']}"]
            for i, s in enumerate(matched["steps"], 1):
                lines.append(f"{i}. {s}")
            return "\n\n".join(lines)

        gen = lock.get("troubleshooting_general", {})
        lines = [gen.get("description", "【锁机通用排查】")]
        for s in gen.get("steps", []):
            lines.append(s)
        return "\n\n".join(lines)

    lines: List[str] = []
    prereqs = lock.get("prerequisites", [])
    if prereqs:
        lines.append("**前置条件**")
        for p in prereqs:
            lines.append(f"- {p}")

    steps_data = lock.get("steps", [])
    if steps_data:
        lines.append("\n**操作步骤**")
        for s in steps_data:
            lines.append(f"\n**第{s.get('step', '?')}步：{s.get('title', '')}**")
            lines.append(s.get("detail", ""))

    notes = lock.get("notes", [])
    if notes:
        lines.append("\n**注意事项**")
        for n in notes:
            lines.append(f"- {n}")
    return "\n".join(lines)


# ====== 平台规则 ======

def _query_rules(msg: str) -> str:
    rules = load_platform_rules()
    if not rules:
        return "老板，规则文件我暂时找不到，稍等下哈～"

    msg_lower = msg.lower()

    if any(kw in msg_lower for kw in ["pc端", "电脑端", "电脑", "新机下单", "旧机下单", "远程下单", "不在店"]):
        pc = rules.get("pc_order_process", {})
        if pc:
            lines = ["老板，PC端下单流程如下：\n"]
            new_steps = pc.get("new_phone_steps", [])
            if new_steps:
                lines.append("## 新机下单\n")
                for s in new_steps:
                    lines.append(f"- {s}")
            old_steps = pc.get("old_phone_steps", [])
            if old_steps:
                lines.append("\n## 旧机下单\n")
                for s in old_steps:
                    lines.append(f"- {s}")
            tier234 = pc.get("tier_234_rules", {})
            if tier234:
                lines.append("\n## 2/3/4折下单规则\n")
                for r in tier234.get("rules", []):
                    lines.append(f"- {r}")
            tier56 = pc.get("tier_56_rules", {})
            if tier56:
                lines.append("\n## 5/6折下单规则\n")
                for r in tier56.get("rules", []):
                    lines.append(f"- {r}")
            insp = pc.get("inspection", {})
            if insp:
                lines.append("\n## 验机须知\n")
                for r in insp.get("rules", []):
                    lines.append(f"- {r}")
            remote = pc.get("remote_order", {})
            if remote:
                lines.append("\n## 客户不在店时\n")
                for r in remote.get("rules", []):
                    lines.append(f"- {r}")
            return "\n".join(lines)

    if any(kw in msg_lower for kw in ["首付", "结算", "会员"]) and "settlement_rules" in rules:
        sr = rules["settlement_rules"]
        lines = ["老板，首付和结算规则如下："]
        for r in sr.get("rules", []):
            lines.append(f"  - {r}")
        for ex in sr.get("examples", []):
            lines.append(f"  {ex['scenario']}：{ex['detail']}")
        return "\n".join(lines)

    if any(kw in msg_lower for kw in ["办单", "下单", "流程"]) and "rental_process" in rules:
        rp = rules["rental_process"]
        lines = [f"老板，办单流程（{len(rp['steps'])}步）："]
        for i, s in enumerate(rp["steps"], 1):
            lines.append(f"  {i}. {s}")
        return "\n".join(lines)

    if any(kw in msg_lower for kw in ["入驻", "开店", "注册"]) and "shop_registration" in rules:
        sr = rules["shop_registration"]
        lines = [f"老板，入驻流程（{len(sr['steps'])}步）："]
        for i, s in enumerate(sr["steps"], 1):
            lines.append(f"  {i}. {s}")
        return "\n".join(lines)

    if any(kw in msg_lower for kw in ["签约", "合同"]) and "contract_signing" in rules:
        cs = rules["contract_signing"]
        lines = [f"老板，签约流程（{len(cs['steps'])}步）："]
        for i, s in enumerate(cs["steps"], 1):
            lines.append(f"  {i}. {s}")
        return "\n".join(lines)

    if any(kw in msg_lower for kw in ["返点", "奖励", "佣金", "提现"]) and "merchant_rewards" in rules:
        mr = rules["merchant_rewards"]
        lines = ["老板，办单返点规则："]
        lines.append(f"  {mr['detail']}")
        for k, v in mr.items():
            if k != "detail" and isinstance(v, dict):
                lines.append(f"  {v['condition']}：{v['rule']}")
        if "red_lines" in rules:
            related = [r for r in rules["red_lines"] if any(w in r for w in ["提现", "超", "兑付", "承诺"])]
            if related:
                lines.append("\n红线（严禁！）：")
                lines.extend([f"  - {r}" for r in related])
        return "\n".join(lines)

    if any(kw in msg_lower for kw in ["费率", "档位", "几折", "服务费"]) and "app_tiers" in rules:
        lines = ["老板，APP端档位费率："]
        for t in rules["app_tiers"]["tiers"]:
            lines.append(f"  {t['name']}：6期费率{t['rate_6']}，12期费率{t['rate_12']}，首付{t['min_down']}")
        return "\n".join(lines)

    if "rules" in rules:
        for k, v in rules["rules"].items():
            if isinstance(v, dict) and v.get("description"):
                kw_check = k.replace("设备管理费", "管理费").replace("客户资质", "资质").replace("办理条件", "条件")
                if any(w in msg_lower for w in kw_check.split("_")):
                    return f"老板，{k}：{v['description']}"
        descs = [
            f"  - {k}：{v['description']}"
            for k, v in rules["rules"].items()
            if isinstance(v, dict) and v.get("description")
        ]
        if descs:
            return "老板，平台规则一览：\n" + "\n".join(descs)

    if "红线" in msg_lower and "red_lines" in rules:
        lines = ["老板，平台红线（绝对不能碰）："]
        for i, r in enumerate(rules["red_lines"], 1):
            lines.append(f"  {i}. {r}")
        return "\n".join(lines)

    return "老板，这个问题在我的知识库里没找到准确答案。你可以问'怎么办单'、'首付谁收'、'费率多少'这些～"


# ====== 手机参数 ======

def _query_specs(model: str) -> str:
    if not model:
        return "老板，告诉我具体型号哈，比如'15 Pro'、'16 Max'～"

    specs = load_phone_specs()
    if specs is None:
        return "老板，参数库暂时找不到了～"

    mk = model.lower().replace("iphone", "").strip()

    found = None
    if isinstance(specs, list):
        for s in specs:
            if isinstance(s, dict) and mk in s.get("model", "").lower():
                found = s
                break
    elif isinstance(specs, dict):
        for k, v in specs.items():
            if mk in k.lower():
                found = v
                break

    if not found:
        return f"老板，没找到 {model} 的参数。我只熟悉苹果 iPhone 系列哈～"

    lines = [f"老板，{found.get('model', model) if isinstance(found, dict) else model} 核心参数："]
    key_fields = [
        "上市时间", "处理器", "屏幕", "刷新率", "前置摄像头", "后置摄像头",
        "电池", "重量", "5G", "接口", "可选颜色", "卖点",
    ]
    if isinstance(found, dict):
        for field in key_fields:
            if field in found:
                lines.append(f"  {field}：{found[field]}")
        for k, v in found.items():
            if k not in key_fields and k != "model":
                lines.append(f"  {k}：{v}")
    else:
        lines.append(json.dumps(found, ensure_ascii=False, indent=2))
    return "\n".join(lines)
