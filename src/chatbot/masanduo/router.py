"""意图路由：关键词匹配，秒级响应。红线优先 → 复合推演 → 各业务意图 → chat 兜底。"""

from __future__ import annotations

import re

from chatbot.masanduo.extract import extract_model

_BUSINESS_INTENTS = {"buyback", "rental", "composite", "inventory", "specs", "pricing", "rules"}

_CHAT_ONLY = [
    "你好", "在吗", "哈喽", "hello", "hi", "早上好", "下午好", "晚上好", "早", "晚安", "谢谢", "拜拜", "再见",
]
_CONFIRM_WORDS = ["好", "可以", "ok", "嗯", "哦", "行", "是的", "对", "没错", "要", "算", "做", "出", "办"]


def is_smalltalk(msg: str) -> bool:
    """纯打招呼/确认词，无需走 RAG，给快速人设回复即可。"""
    s = msg.lower().replace(" ", "").strip()
    return s in _CHAT_ONLY or s in _CONFIRM_WORDS


def route(msg: str, last_intent: str = "") -> str:
    """返回意图名。last_intent 用于确认词/简短追问的上下文延续。"""
    msg_lower = msg.lower().replace(" ", "")
    has_model = extract_model(msg)
    has_budget = bool(
        re.search(r"(?<!\d)\d{3,5}(?!\d)", msg)
        or re.search(r"[一二三四五六七八九]千", msg.lower())
        or any(
            kw in msg_lower
            for kw in ["三千", "五千", "八百", "一千", "两千", "四千", "六千", "七千", "八千", "九千"]
        )
    )

    # 0. 最高优先级：套机/监管机拦截
    if any(kw in msg_lower for kw in ["套机", "套现", "套你们", "能不能套", "怎么套", "帮忙套", "套个机"]):
        return "套机风险"
    if any(kw in msg_lower for kw in ["监管机", "监管", "有锁机", "配置锁"]):
        return "监管机"

    # 0.5 复合推演
    if has_model and any(
        kw in msg_lower for kw in ["想办", "想买", "置换", "换新", "以旧换新", "抵", "换", "推荐档位", "推荐"]
    ):
        return "composite"
    if has_model and has_budget and any(
        kw in msg_lower
        for kw in [
            "能办吗", "能不能办", "能办不", "够不够", "可以办吗", "能办理吗", "过不过", "过得了",
            "能上", "上不上", "能拿", "够上", "能换",
        ]
    ):
        return "composite"
    if has_budget and any(
        kw in msg_lower for kw in ["能做什么", "能买什么", "可以买", "推荐", "办个", "办什么", "能办什么", "算算"]
    ):
        return "composite"

    # 1. 回收价
    if any(kw in msg_lower for kw in ["回收价", "回收", "二手价", "卖多少", "值多少", "靓机汇", "卖给你们", "旧机"]):
        return "buyback"

    # 2. 库存
    if any(kw in msg_lower for kw in ["库存", "有货", "有什么机", "有什么库存", "全部库存"]):
        return "inventory"

    # 3. 定价分析（必须在"多少钱"之前）
    if any(kw in msg_lower for kw in ["加多少钱", "怎么定价", "卖多少合适", "零售", "怎么卖"]):
        return "pricing"

    # 4. 售价/库存
    if any(kw in msg_lower for kw in ["多少钱", "什么价"]):
        return "inventory"

    # 5. 租机计算
    if any(kw in msg_lower for kw in ["算一下", "租机", "几折", "几期", "月供", "费用", "分期", "折"]):
        return "rental"

    # 6. 海报（已砍掉外部图像服务，但保留路由提示，由 compute 给降级文案）
    if any(kw in msg_lower for kw in ["海报", "宣传图", "推广图"]):
        return "poster"

    # 7. 规则/锁机
    if any(
        kw in msg_lower
        for kw in [
            "费率", "办单", "下单", "结算", "返点", "首付", "规则", "入驻", "签约", "合同",
            "红线", "租机模式", "锁机", "上锁", "configurator", "无锁头", "证书无效", "电脑", "pc", "远程",
        ]
    ):
        if any(kw in msg_lower for kw in ["锁机", "上锁", "configurator", "无锁头", "证书无效"]):
            return "lock"
        return "rules"

    # 7.5 平台优势/为什么选你 → chat
    if any(kw in msg_lower for kw in ["为什么选", "优势", "有什么好", "你家", "你们家", "你们这边", "你们这"]):
        return "chat"

    # 7.6 验机相关
    if any(kw in msg_lower for kw in ["验机", "不愿意验", "非要验"]):
        return "sales_tips"

    # 8. 销售策略
    if any(
        kw in msg_lower
        for kw in ["怎么提高", "怎么多卖", "销售技巧", "怎么推", "话术", "营销", "怎么说", "客户说", "推销"]
    ):
        return "sales_tips"

    # 9. 参数/卖点/对比
    if any(
        kw in msg_lower
        for kw in [
            "参数", "配置", "处理器", "摄像头", "颜色", "屏幕", "电池", "卖点", "介绍",
            "怎么样", "值得买", "对比", "比较", "区别", "怎么选",
        ]
    ):
        return "specs"

    # 9.5 门店概况
    if any(kw in msg_lower for kw in ["门店", "入驻", "概况", "维修店", "综合店", "卖场", "档口", "回收渠道", "流通"]):
        return "store_overview"

    # 9.6 经营干货
    if any(
        kw in msg_lower
        for kw in [
            "怎么经营", "怎么开", "没生意", "没什么生意", "生意不好", "生意差", "没客户", "怎么赚钱",
            "多赚", "引流", "抖音", "美团", "小红书", "大众点评", "闪购", "留住客户", "老客户",
            "薪酬", "员工", "团队", "进货", "定价", "出路", "行情", "难做", "不行了",
        ]
    ):
        return "biz_knowledge"

    # 9.7 电商素材
    if any(
        kw in msg_lower
        for kw in [
            "闲鱼", "淘宝", "拼多多", "转转", "电商主图", "商品描述", "素材", "产品识别",
            "电商海报", "电商素材", "做图", "出图",
        ]
    ):
        return "ecommerce"

    # 9.8 人工客服
    if any(kw in msg_lower for kw in ["人工", "客服", "转人工", "真人"]):
        return "human_agent"

    # 10. 上下文延续
    if msg_lower.strip() in _CONFIRM_WORDS:
        if last_intent in _BUSINESS_INTENTS:
            return last_intent
        return "chat"

    if msg_lower.strip() in _CHAT_ONLY:
        return "chat"

    followup_keywords = ["这两款", "这两个", "这几款", "那几个", "有没有", "有吗", "店里", "我们店", "多少钱一个", "什么价"]
    if last_intent in _BUSINESS_INTENTS:
        if len(msg.strip()) <= 12:
            return last_intent
        if any(kw in msg_lower for kw in followup_keywords):
            return last_intent if last_intent in {"inventory", "specs", "buyback"} else "inventory"

    return "chat"
