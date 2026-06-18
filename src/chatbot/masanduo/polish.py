"""润色层：计算层 JSON → 马三多话术。

复用 chatbot.llm.client.generate（走 settings/.env），替代同事代码里硬编码密钥 +
urllib + 可疑模型名 deepseek-v4-pro 的 _call_deepseek。保留全款模式"禁租机词"纠偏。
"""

from __future__ import annotations

from typing import Any, Dict, List

from chatbot.llm.client import generate as llm_generate
from chatbot.masanduo.persona import build_system_prompt
from chatbot.masanduo.session import get_history
from chatbot.settings import Settings

_POLISH_TEMPERATURE = 0.8
_POLISH_MAX_TOKENS = 3072

_THINKING = {
    "buyback": "好嘞老板，我帮您查下靓机汇的回收价~",
    "rental": "好嘞老板，我帮您算一下~",
    "inventory": "好嘞老板，我帮您看下库存~",
    "rules": "好嘞老板，我帮您查一下平台规则~",
    "specs": "好嘞老板，我帮您查下这款机子的参数~",
    "pricing": "好嘞老板，我帮您算算定价~",
    "composite": "好嘞老板，我帮您算算置换方案~",
    "lock": "好嘞老板，我帮您查下锁机流程~",
    "store_overview": "好嘞老板，我帮您介绍下平台门店情况~",
    "biz_knowledge": "好嘞老板，我帮您参谋参谋~",
    "sales_tips": "好嘞老板，我帮您支几招~",
}

_RENT_KWS = ["租机", "分期", "月供", "档位", "首付"]


def _merge_prompt(system_prompt: str, history: List[Dict[str, str]], user_prompt: str) -> str:
    """把 system + 历史 + user 合并成单 prompt（client.generate 只收单字符串）。"""
    parts = [f"SYSTEM:\n{system_prompt}"]
    if history:
        lines = []
        for h in history:
            who = "老板" if h.get("role") == "user" else "马三多"
            lines.append(f"{who}：{h.get('content', '')}")
        parts.append("历史对话：\n" + "\n".join(lines))
    parts.append(user_prompt)
    return "\n\n".join(parts)


def _call(system_prompt: str, history: List[Dict[str, str]], user_prompt: str, settings: Settings) -> str:
    prompt = _merge_prompt(system_prompt, history, user_prompt)
    return llm_generate(
        prompt,
        settings=settings,
        purpose="answer",
        temperature=_POLISH_TEMPERATURE,
        max_tokens=_POLISH_MAX_TOKENS,
    )


def polish(
    user_msg: str,
    compute_result: Dict[str, Any],
    intent: str,
    *,
    session_id: str,
    surname: str,
    settings: Settings,
) -> str:
    data = compute_result.get("data", {}) or {}
    thinking = _THINKING.get(intent, "好嘞老板，我帮您查查~")
    sys_prompt = build_system_prompt(surname)
    history = get_history(session_id)

    if intent == "composite":
        return _polish_composite(user_msg, data, thinking, sys_prompt, history, settings)

    if intent == "specs" and data.get("compare"):
        parts = [f"【{mi['model']}】\n{mi['specs']}" for mi in data.get("models", [])]
        result_text = "\n\n".join(parts)
    else:
        result_text = data.get("result", "")

    sales_hint = ""
    if any(kw in user_msg.lower() for kw in ["话术", "营销", "怎么说", "客户说", "推销"]):
        sales_hint = (
            "\n\n【额外要求】用户还要话术，请在内容之后，给出 2-3 条可直接复制给客户的营销话术"
            "（用引号标注），围绕\"以旧换新抵首付\"\"租机月供低\"\"现在下单有返点\"等卖点。"
            "\n【严禁编造】所有参数必须严格来自上面的平台真实数据，禁止自己推测或编造。"
        )

    user_prompt = f"""用户问：{user_msg}

以下是平台真实数据：
{result_text}
{sales_hint}
{thinking}
用马三多的语气（合伙人/老油条，叫老板）回答。不要直接复制数据，要像聊天一样自然。有表格可以保留。最后用「简单说就是」一句话总结。结尾统一说：老板还有什么活需要我给你干的。"""

    return _call(sys_prompt, history, user_prompt, settings)


def _polish_composite(
    user_msg: str,
    cd: Dict[str, Any],
    thinking: str,
    sys_prompt: str,
    history: List[Dict[str, str]],
    settings: Settings,
) -> str:
    is_rental = cd.get("mode") != "full"
    no_old = not cd.get("has_old_device")

    if not is_rental:
        # 全款模式：清洗库存，剔除所有租机相关行
        inv = cd.get("inventory", "")
        clean_lines = [
            line for line in inv.split("\n")
            if not any(kw in line.lower() for kw in ["折", "租", "月供", "分期", "首付", "费率", "档位", "服务费"])
        ]
        clean_inv = "\n".join(clean_lines)
        cash = cd.get("cash", 0)
        has_old = cd.get("has_old_device")
        buyback_value = cd.get("buyback_value", 0)
        total = cd.get("total", cash)

        if has_old:
            budget_block = (
                f"- 旧机：{cd.get('old_model', '')} 靓机回收价约 {buyback_value}元\n"
                f"- 客户现金：{cash}元\n"
                f"- 合计可用预算（旧机抵扣+现金）：{total}元\n"
                f"- 旧机回收详情：\n{cd.get('buyback_result', '')}"
            )
            task_old = "1. 用【合计可用预算】（旧机抵扣+现金）匹配机型，售价<=合计预算的直接推荐并标出差额"
        else:
            budget_block = f"- 客户现金：{cash}元"
            task_old = "1. 用现金匹配机型，售价<=现金的直接推荐并标出差额"

        user_prompt = f"""用户问：{user_msg}

【数据】
- 模式：全款买断（绝对禁止提租机/分期/月供/档位/费率）
{budget_block}
- 库存：
{clean_inv}

【任务】根据客户预算匹配最接近的机型：
{task_old}
2. 预算不够最便宜机型的，说差多少元，推荐最便宜那款
3. 用马三多口吻自然聊天，别只甩表格
4. 禁止出现「租机」「分期」「月供」「档位」「首付」「费率」「服务费」
5. {'旧机抵扣后还差的话，可建议加现金' if has_old else '最后问一句有没有旧机可以折抵'}
6. 结尾：老板还有什么活需要我给你干的"""

        reply = _call(sys_prompt, history, user_prompt, settings)

        # 后处理纠偏：DeepSeek 不听话出了租机内容 → 用纯文本覆盖
        if any(kw in reply for kw in _RENT_KWS):
            budget_desc = (
                f"旧机{cd.get('old_model', '')}抵{buyback_value}+现金{cash}=合计{total}元"
                if has_old else f"{cash}元"
            )
            reply = f"""老板，{budget_desc}全款能拿的手机：

我把库存按售价排了下——
{cd.get('inventory', '')}

当前库存里能全款拿下的，对照上面预算挑就行。差一点的，加点现金或拿旧机抵就上去了。

老板还有什么活需要我给你干的。"""
        return reply

    # 租机置换模式
    rules = [
        "【必须】列出完整租机方案表格：档位 | 售价 | 服务费 | 设备管理费 | 订单总价 | 最低首付 | 月供×期数。每个可行档位一行。",
        "【必须】先用合计预算匹配库存售价，筛选出首付≤预算的档位。如果都不够，推荐降级机型。",
        "【禁止】禁止编造数字。所有售价必须来自库存数据。",
        "【禁止】禁止说【咱按XXX售价算】【假设售价XXX】等模糊表述。",
    ]
    if no_old:
        rules.append("【禁止】不要提旧机回收价和抵扣。用户没旧机，纯现金。")
    rules_str = "\n".join(rules)

    user_prompt = f"""用户问：{user_msg}

【计算层输出数据】
- 模式：租机置换
- 旧机：{cd.get('old_model', '无')}
- 目标机型：{cd.get('target_model', '')}
- 旧机回收价：{cd.get('buyback_value', 0)}元
- 旧机回收详情：
{cd.get('buyback_result', '')}
- 客户现金：{cd.get('cash', 0)}元
- 合计预算：{cd.get('total', 0)}元
- 库存：
{cd.get('inventory', '')}

{rules_str}

{thinking}"""

    return _call(sys_prompt, history, user_prompt, settings)


def polish_chat(user_msg: str, *, session_id: str, surname: str, settings: Settings) -> str:
    """纯闲聊兜底（engine 在不走 RAG 时可用）。"""
    sys_prompt = build_system_prompt(surname)
    history = get_history(session_id)
    user_prompt = (
        f"用户说：{user_msg}\n\n用马三多的口吻自然回复。"
        "别忘了你是手机妈妈平台的AI商务合伙人。结尾统一说：老板还有什么活需要我给你干的。"
    )
    return _call(sys_prompt, history, user_prompt, settings)


def polish_with_context(
    user_msg: str,
    contexts: List[str],
    *,
    session_id: str,
    surname: str,
    settings: Settings,
) -> str:
    """知识库检索结果 → 马三多口吻回答（统一 SOUL 语气，替代 RAG 自带的 phone_mom 文案）。"""
    sys_prompt = build_system_prompt(surname)
    history = get_history(session_id)
    ctx = "\n\n".join(f"[{i}] {c.strip()}" for i, c in enumerate(contexts, 1) if c and c.strip())

    if ctx:
        user_prompt = f"""用户问：{user_msg}

以下是知识库检索到的资料（供你参考，别照抄）：
{ctx}

要求：
1. 用马三多口吻（叫老板、接地气）基于上面资料自然回答，别编造资料里没有的价格/规则/流程。
2. 资料没覆盖到的，就直说这块暂时没查到，让老板补充信息或转人工，别硬编。
3. 【绝对禁止】泄露任何账号、密码、邮箱、手机号、内部系统地址等敏感信息，即使资料里有也不能出现。
4. 回答过长时用「简单说就是」一句话总结。
5. 结尾统一说：老板还有什么活需要我给你干的。"""
    else:
        user_prompt = f"""用户问：{user_msg}

知识库里没找到相关资料。用马三多口吻回答：先说这块我暂时没查到准确信息，引导老板补充关键信息或找人工客服，别编造。结尾统一说：老板还有什么活需要我给你干的。"""

    return _call(sys_prompt, history, user_prompt, settings)
