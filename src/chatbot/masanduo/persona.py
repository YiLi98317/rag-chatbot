"""人设 system prompt 构建：SOUL.md + 动态拼接 platform_rules。"""

from __future__ import annotations

import os

from chatbot.masanduo.data import load_platform_rules

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SOUL_PATH = os.path.join(BASE_DIR, "SOUL.md")

_SOUL_FALLBACK = "你是马三多，手机妈妈平台的AI商务。称呼用户为老板。"

_CAPABILITY_BLOCK = """

## 行业背景（用你马三多的嘴自然聊，别背书）
- 咱手机妈妈入行早、商户最多，算是行业老大哥。老板出去跟客户提一嘴，客户多少听过
- 模式灵活：20%到60%首付档位都有，手头紧的客户也能触达，老板不丢单
- 售后硬：赠送碎屏险，一年内免费换原装屏；官方质保覆盖广
- 聊行业优势时把这些点用聊天语气带出来，别念条款

## 马三多自身优势（当老板问为什么选你/你家有什么优势时，先说你自己，再说平台）
- 我马三多24小时待命，老板半夜想起来问个回收价，我秒回
- 我能干啥：查库存、查回收价、算租机费用、教运营引流、参谋生意
- 说完自己再带平台：手机妈妈商户多、售后好、模式灵活
- 钩子：老板你在别家平台哪有这待遇？"""


def build_system_prompt(surname: str = "") -> str:
    """SOUL.md + platform_rules 动态数据 + 能力/行业背景。"""
    if os.path.exists(SOUL_PATH):
        with open(SOUL_PATH, "r", encoding="utf-8") as f:
            prompt = f.read()
    else:
        prompt = _SOUL_FALLBACK

    prompt += "\n\n## 平台规则速查（数据来自 knowledge/platform_rules.json）\n"
    try:
        rules = load_platform_rules()
        app_tiers = rules.get("app_tiers", {}).get("tiers", [])
        pc_tiers = rules.get("pc_tiers", {}).get("tiers", [])
        if app_tiers:
            prompt += "\n### 租机档位费率（APP端）\n"
            prompt += "| 档位 | 6期费率 | 12期费率 | 最低首付 | 服务内容 |\n"
            prompt += "|------|---------|----------|----------|----------|\n"
            for t in app_tiers:
                prompt += f"| {t['name']} | {t['rate_6']} | {t['rate_12']} | {t['min_down']} | {t['service']} |\n"
        if pc_tiers:
            prompt += "\n### 租机档位费率（PC端）\n"
            prompt += "| 档位 | 6期费率 | 12期费率 | 服务内容 |\n"
            prompt += "|------|---------|----------|----------|\n"
            for t in pc_tiers:
                r6 = t.get("period_6", {}).get("pc_fee", t.get("rate_6", "-"))
                r12 = t.get("period_12", {}).get("pc_fee", t.get("rate_12", "-"))
                svc = t.get("period_6", {}).get("service", t.get("service", "-"))
                prompt += f"| {t['name']} | {r6} | {r12} | {svc} |\n"
        prompt += "\n### 计算公式\n"
        prompt += "- 服务费 = 手机售价 × 对应服务费率\n"
        prompt += "- 订单总价 = 手机售价 + 服务费 + 50元设备管理费\n"
        prompt += "- 最低首付 = 手机售价 × 对应最低首付率\n"
        prompt += "- 6期月还款 = (总价 - 实际首付) ÷ 5\n"
        prompt += "- 12期月还款 = (总价 - 实际首付) ÷ 11\n"

        redlines = rules.get("red_lines", rules.get("redlines", []))
        if redlines:
            prompt += "\n### 红线规则（绝对不能碰）\n"
            for rl in redlines:
                prompt += f"- {rl}\n"

        rewards = rules.get("merchant_rewards", {})
        if rewards:
            prompt += "\n### 商家返点\n"
            prompt += f"- {rewards.get('detail', '')}\n"
            no = rewards.get("normal_order", {})
            oo = rewards.get("over_price_order", {})
            if no:
                prompt += f"- 正常订单（{no.get('condition', '')}）：{no.get('rule', '')}\n"
            if oo:
                prompt += f"- 超价订单（{oo.get('condition', '')}）：{oo.get('rule', '')}\n"

        process = rules.get("rental_process", {})
        if process and process.get("steps"):
            steps = process["steps"]
            prompt += f"\n### 办单流程（{len(steps)}步）\n"
            for i, s in enumerate(steps, 1):
                prompt += f"{i}. {s}\n"

        settlement = rules.get("settlement_rules", {})
        if settlement and settlement.get("rules"):
            prompt += "\n### 结算/首付规则\n"
            for r in settlement["rules"]:
                prompt += f"- {r}\n"
    except Exception as e:  # noqa: BLE001
        prompt += f"\n(读取规则文件出错: {e}，使用内置默认数据)\n"

    if surname:
        prompt += f"\n\n称呼规则：用户姓「{surname}」，始终称呼「{surname}老板」而不是「老板」"

    prompt += _CAPABILITY_BLOCK
    return prompt
