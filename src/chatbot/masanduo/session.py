"""多轮会话状态层。

按 session_id 保存推演上下文（budget/target/old_device/last_intent）与对话历史，
支持复合推演跨轮记忆、容量追问、确认词延续，并定期清理过期会话。
内存实现：单进程 CLI / 单实例服务足够；多实例需替换为外部存储。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List

_LOCK = threading.Lock()
_STATE: Dict[str, Dict[str, Any]] = {}
_HISTORY: Dict[str, List[Dict[str, str]]] = {}
_TOUCHED: Dict[str, float] = {}

MAX_HISTORY = 10  # 每会话最多保留 10 轮（20 条消息）
SESSION_TTL_S = 2 * 3600


def _new_state() -> Dict[str, Any]:
    return {
        "budget": 0,
        "target": "",
        "old_device": "",
        "last_intent": "",
        "rounds": 0,
    }


def get_state(session_id: str) -> Dict[str, Any]:
    with _LOCK:
        _TOUCHED[session_id] = time.time()
        return _STATE.setdefault(session_id, _new_state())


def update_state(session_id: str, **kwargs: Any) -> Dict[str, Any]:
    with _LOCK:
        s = _STATE.setdefault(session_id, _new_state())
        s.update(kwargs)
        s["rounds"] = s.get("rounds", 0) + 1
        _TOUCHED[session_id] = time.time()
        return s


def get_history(session_id: str) -> List[Dict[str, str]]:
    with _LOCK:
        return list(_HISTORY.get(session_id, []))


def save_turn(session_id: str, user_msg: str, reply: str) -> None:
    with _LOCK:
        hist = _HISTORY.setdefault(session_id, [])
        hist.append({"role": "user", "content": user_msg})
        hist.append({"role": "assistant", "content": reply})
        if len(hist) > MAX_HISTORY * 2:
            _HISTORY[session_id] = hist[-(MAX_HISTORY * 2):]
        _TOUCHED[session_id] = time.time()


def cleanup(now: float | None = None) -> int:
    """清理过期会话，返回清理数量。"""
    now = now if now is not None else time.time()
    removed = 0
    with _LOCK:
        for sid in list(_TOUCHED.keys()):
            if now - _TOUCHED[sid] > SESSION_TTL_S:
                _STATE.pop(sid, None)
                _HISTORY.pop(sid, None)
                _TOUCHED.pop(sid, None)
                removed += 1
    return removed


def clear(session_id: str) -> None:
    with _LOCK:
        _STATE.pop(session_id, None)
        _HISTORY.pop(session_id, None)
        _TOUCHED.pop(session_id, None)
