"""
Parser for Netease Qiyu (网易七鱼) customer service chat exports.

Handles pre-processed Excel exports (HTML tags already stripped) with 16 columns.
Cleans residual JSON messages, system prompts, and URLs from the conversation content.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

_MSG_HEADER_RE = re.compile(
    r"^(.+?)\s{2,}(\d{4}年\d{2}月\d{2}日\s+\d{2}:\d{2}:\d{2})\s*$",
    re.MULTILINE,
)

_TRANSFER_PHRASES = (
    "转接成功，请您不要退出此页面",
    "转接成功,请您不要退出此页面",
)

_URL_ONLY_RE = re.compile(r"^\s*https?://\S+\s*$")

_DISCARD_SENTINEL = ""


@dataclass
class Message:
    sender: str
    timestamp: str
    text: str
    role: str  # "agent" or "user"


@dataclass
class ParsedSession:
    session_id: str
    agent_name: str
    visitor_name: str
    rounds: int
    messages: List[Message] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


def _try_extract_cmd65_content(text: str) -> Optional[str]:
    stripped = text.strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return None
    try:
        obj = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return None
    if obj.get("cmd") == 65:
        content = str(obj.get("content", "")).strip()
        return content if content else _DISCARD_SENTINEL
    return None


def _is_system_json(text: str) -> bool:
    stripped = text.strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return False
    try:
        obj = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        if '"cmd"' in stripped and '"evaluation' in stripped:
            return True
        return False
    cmd = obj.get("cmd")
    if cmd is not None and cmd != 65:
        return True
    if "evaluation_auto_popup" in obj:
        return True
    return False


def _is_transfer_message(text: str) -> bool:
    stripped = text.strip()
    return any(stripped.startswith(p) for p in _TRANSFER_PHRASES)


def _is_url_only(text: str) -> bool:
    return bool(_URL_ONLY_RE.match(text))


def _split_messages(raw_content: str, agent_name: str) -> List[Message]:
    messages: List[Message] = []
    headers = list(_MSG_HEADER_RE.finditer(raw_content))
    if not headers:
        return messages

    for i, match in enumerate(headers):
        sender = match.group(1).strip()
        timestamp = match.group(2).strip()
        body_start = match.end()
        body_end = headers[i + 1].start() if i + 1 < len(headers) else len(raw_content)
        body = raw_content[body_start:body_end].strip()

        role = "agent" if sender == agent_name else "user"
        messages.append(Message(sender=sender, timestamp=timestamp, text=body, role=role))

    return messages


def _clean_message(msg: Message) -> Optional[Message]:
    text = msg.text

    if _is_system_json(text):
        return None

    if _is_transfer_message(text):
        return None

    cmd65_content = _try_extract_cmd65_content(text)
    if cmd65_content is not None:
        if cmd65_content == _DISCARD_SENTINEL:
            return None
        return Message(sender=msg.sender, timestamp=msg.timestamp, text=cmd65_content, role=msg.role)

    if _is_url_only(text):
        return None

    if not text.strip():
        return None

    return msg


def parse_session(
    session_id: str,
    agent_name: str,
    visitor_name: str,
    rounds: int,
    raw_content: str,
    extra_metadata: Optional[dict] = None,
) -> Optional[ParsedSession]:
    if not raw_content or not raw_content.strip():
        return None

    raw_messages = _split_messages(raw_content, agent_name)
    cleaned: List[Message] = []
    for msg in raw_messages:
        result = _clean_message(msg)
        if result is not None:
            cleaned.append(result)

    if not cleaned:
        return None

    return ParsedSession(
        session_id=str(session_id),
        agent_name=agent_name,
        visitor_name=visitor_name,
        rounds=rounds,
        messages=cleaned,
        metadata=extra_metadata or {},
    )


def session_to_knowledge_doc(session: ParsedSession) -> Optional[str]:
    agent_lines: List[str] = []
    for msg in session.messages:
        if msg.role == "agent":
            text = msg.text.strip()
            if text and len(text) > 3:
                agent_lines.append(f"- {text}")

    if not agent_lines:
        return None

    header = f"[客服指导] 客服: {session.agent_name} | 回合数: {session.rounds}"
    return header + "\n\n" + "\n".join(agent_lines)


def session_to_conversation_doc(session: ParsedSession) -> Optional[str]:
    lines: List[str] = []
    for msg in session.messages:
        role_label = "客服" if msg.role == "agent" else "用户"
        text = msg.text.strip()
        if text:
            lines.append(f"{role_label}: {text}")

    if not lines:
        return None

    header = f"[对话记录] 客服: {session.agent_name} | 回合数: {session.rounds}"
    return header + "\n\n" + "\n".join(lines)
