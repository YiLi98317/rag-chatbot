"""knowledge JSON 加载器。

所有数据文件位于本子包的 knowledge/ 下，自包含，不依赖外部目录。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

KNOWLEDGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge")


def _path(name: str) -> str:
    return os.path.join(KNOWLEDGE_DIR, name)


def load_json(name: str) -> Optional[Any]:
    path = _path(name)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_buyback_prices() -> Optional[Dict[str, Any]]:
    return load_json("buyback_prices.json")


def load_platform_rules() -> Dict[str, Any]:
    return load_json("platform_rules.json") or {}


def load_phone_specs() -> Any:
    return load_json("phone_specs.json")


_DEFAULT_INVENTORY: List[Dict[str, Any]] = [
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


def load_inventory() -> List[Dict[str, Any]]:
    data = load_json("inventory.json")
    if isinstance(data, list) and len(data) > 0:
        return data
    return list(_DEFAULT_INVENTORY)
