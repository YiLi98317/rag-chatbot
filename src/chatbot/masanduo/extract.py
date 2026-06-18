"""型号提取：俗称→标准型号映射 + 正则保底。"""

from __future__ import annotations

import re

# 俗称 → 标准型号映射（先整体匹配，禁止切碎）
ALIAS_MAP = {
    "16pm": "16 Pro Max",
    "16promax": "16 Pro Max",
    "16pro": "16 Pro",
    "15pm": "15 Pro Max",
    "15promax": "15 Pro Max",
    "15pro": "15 Pro",
    "14pm": "14 Pro Max",
    "14promax": "14 Pro Max",
    "14pro": "14 Pro",
    "13pm": "13 Pro Max",
    "13promax": "13 Pro Max",
    "13pro": "13 Pro",
    "12pm": "12 Pro Max",
    "12promax": "12 Pro Max",
    "12pro": "12 Pro",
    "11pm": "11 Pro Max",
    "11promax": "11 Pro Max",
    "11pro": "11 Pro",
    "16plus": "16 Plus",
    "15plus": "15 Plus",
    "14plus": "14 Plus",
}


def extract_model(msg: str) -> str:
    """从消息中提取手机型号。"""
    msg_lower = msg.lower().replace(" ", "").replace("iphone", "").replace("苹果", "")

    for alias in sorted(ALIAS_MAP.keys(), key=len, reverse=True):
        if alias in msg_lower:
            return ALIAS_MAP[alias]

    pure_digit = re.search(r"^(\d{1,2})$", msg_lower)
    if pure_digit:
        v = int(pure_digit.group(1))
        if 8 <= v <= 17:
            return str(v)

    patterns = [
        r"(\d{1,2}\s*(?:pro\s*max|pro|plus|mini|air|e)?)",
        r"(se\d?)",
        r"(xr?)",
        r"(xs\s*max|xs)",
        r"(\d{1,2})(?:\s*(?:的|回收|二手|价格|多少))",
    ]
    for p in patterns:
        m = re.search(p, msg, re.IGNORECASE)
        if m:
            model = m.group(1).strip()
            if model.isdigit():
                v = int(model)
                if v < 8 or v > 17:
                    continue
            return model
    return ""
