from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import pandas as pd

from chatbot.ingest.chunking import chunk_text_en, chunk_text_zh
from chatbot.retrieval.normalize import detect_lang


def iter_files(root: str, extensions: Tuple[str, ...] = (".txt", ".md", ".xlsx")) -> Iterable[Path]:
    base = Path(root)
    for path in base.rglob("*"):
        if not (path.is_file() and path.suffix.lower() in extensions):
            continue
        # 跳过模板与说明文件，避免被当作知识 ingest
        if "_templates" in path.parts or path.name.upper() == "README.MD":
            continue
        yield path


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


# 治理版知识库：从 frontmatter 提取的元数据字段（用于观测/未来按角色过滤）。
_FM_META_KEYS = ("doc_id", "title", "visible_to", "risk_level", "owner", "version", "category")


def parse_frontmatter(raw: str) -> Tuple[Dict[str, Any], str]:
    """解析 markdown 顶部 --- frontmatter ---，返回 (meta, body)。

    无 frontmatter 时 meta 为空、body 原样返回（向后兼容旧知识库.md）。
    """
    lines = raw.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, raw
    meta: Dict[str, Any] = {}
    body_start = None
    for i, ln in enumerate(lines[1:], start=1):
        if ln.strip() == "---":
            body_start = i + 1
            break
        if ":" not in ln:
            continue
        key, _, val = ln.partition(":")
        key = key.strip()
        val = val.strip()
        if " #" in val:  # 去行内注释
            val = val.split(" #", 1)[0].strip()
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            meta[key] = [x.strip() for x in inner.split(",") if x.strip()]
        elif val:
            meta[key] = val
    if body_start is None:  # 没有闭合的 ---，视为无 frontmatter
        return {}, raw
    return meta, "\n".join(lines[body_start:])


def _kb_extra_meta(fm: Dict[str, Any]) -> Dict[str, Any]:
    """把 frontmatter 映射为附加 metadata。注意：不覆盖 source_type（保持 'file' 以免打断 KB 检索）。"""
    extra: Dict[str, Any] = {}
    for k in _FM_META_KEYS:
        if k in fm and fm[k] not in (None, "", []):
            extra[k] = fm[k]
    # frontmatter 里的 source_type 是文档类型(faq/rule...)，存为 doc_type，避免与检索用的 source_type 冲突
    doc_type = fm.get("source_type") or fm.get("category")
    if doc_type:
        extra["doc_type"] = doc_type
    return extra


def _row_to_text(row: Dict[str, Any]) -> str:
    """Convert a spreadsheet row to text (same as reingest_company_xlsx)."""
    parts: List[str] = []
    for k, v in row.items():
        if v is None:
            continue
        s = str(v).strip()
        if not s or s.lower() in {"nan", "none"}:
            continue
        parts.append(f"{k}: {s}")
    return "\n".join(parts).strip()


def _load_xlsx_docs(path: Path, chunk_size: int, chunk_overlap: int) -> List[Dict]:
    """Load .xlsx into doc chunks (same logic as reingest_company_xlsx for consistent outcome)."""
    docs: List[Dict] = []
    zh_chunk_size = int(os.getenv("ZH_CHUNK_SIZE", str(chunk_size)))
    zh_chunk_overlap = int(os.getenv("ZH_CHUNK_OVERLAP", str(chunk_overlap)))
    xl = pd.ExcelFile(path)
    for sheet in xl.sheet_names:
        df = xl.parse(sheet)
        df.columns = [str(c).strip() for c in df.columns]
        for i, row in enumerate(df.to_dict(orient="records")):
            text = _row_to_text(row)
            if not text:
                continue
            lang = detect_lang(text)
            eff_size = zh_chunk_size if lang in ("zh", "mixed") else chunk_size
            eff_overlap = zh_chunk_overlap if lang in ("zh", "mixed") else chunk_overlap
            if lang in ("zh", "mixed"):
                chunks = chunk_text_zh(text, max_chars=eff_size, overlap=eff_overlap)
            else:
                chunks = chunk_text_en(text, max_chars=eff_size, overlap=eff_overlap)
            for ci, chunk in enumerate(chunks):
                docs.append(
                    {
                        "text": chunk,
                        "metadata": {
                            "source": str(path),
                            "chunk": ci,
                            "lang": lang,
                            "source_type": "xlsx",
                            "table": sheet,
                            "sheet": sheet,
                            "row": i,
                        },
                    }
                )
    return docs


def load_and_chunk(root: str, chunk_size: int, chunk_overlap: int) -> List[Dict]:
    docs: List[Dict] = []
    for path in iter_files(root):
        if path.suffix.lower() == ".xlsx":
            docs.extend(_load_xlsx_docs(path, chunk_size, chunk_overlap))
            continue
        raw = read_text(path)
        # 治理版 .md 支持 frontmatter：提取元数据，正文去掉 frontmatter 再分块
        fm: Dict[str, Any] = {}
        body = raw
        if path.suffix.lower() == ".md":
            fm, body = parse_frontmatter(raw)
        extra_meta = _kb_extra_meta(fm) if fm else {}
        lang = detect_lang(body)

        # If user didn't override defaults, allow zh-specific tuning via env vars.
        zh_chunk_size = int(os.getenv("ZH_CHUNK_SIZE", str(chunk_size)))
        zh_chunk_overlap = int(os.getenv("ZH_CHUNK_OVERLAP", str(chunk_overlap)))
        eff_size = chunk_size
        eff_overlap = chunk_overlap
        if lang in ("zh", "mixed") and chunk_size == 800:
            eff_size = zh_chunk_size
        if lang in ("zh", "mixed") and chunk_overlap == 150:
            eff_overlap = zh_chunk_overlap

        if lang in ("zh", "mixed"):
            chunks = chunk_text_zh(body, max_chars=eff_size, overlap=eff_overlap)
        else:
            chunks = chunk_text_en(body, max_chars=eff_size, overlap=eff_overlap)

        for i, chunk in enumerate(chunks):
            meta = {
                "source": str(path),
                "chunk": i,
                "lang": lang,
                "source_type": "file",  # 保持 file：不打断 retriever 的 KB 优先过滤
            }
            meta.update(extra_meta)
            docs.append({"text": chunk, "metadata": meta})
    return docs
