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
        if path.is_file() and path.suffix.lower() in extensions:
            yield path


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


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
        lang = detect_lang(raw)

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
            chunks = chunk_text_zh(raw, max_chars=eff_size, overlap=eff_overlap)
        else:
            chunks = chunk_text_en(raw, max_chars=eff_size, overlap=eff_overlap)

        for i, chunk in enumerate(chunks):
            docs.append(
                {
                    "text": chunk,
                    "metadata": {
                        "source": str(path),
                        "chunk": i,
                        "lang": lang,
                        "source_type": "file",
                    },
                }
            )
    return docs
