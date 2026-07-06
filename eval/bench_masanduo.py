#!/usr/bin/env python3
"""马三多问答 benchmark runner（第一版，规则评分 + 可选 LLM judge）。

只读评测：读 golden → 逐条调用 /v1/qa → 规则打分 → 生成 JSON + Markdown 报告。
不改任何业务代码，不默认打生产地址。

用法：
    python eval/bench_masanduo.py \
      --golden eval/golden_masanduo_v1.jsonl \
      --base-url http://localhost:8000 \
      --output-dir eval/reports

安全：
- 默认 base-url = http://localhost:8000。检测到生产 IP 时会要求显式 --allow-prod。
- 每条请求 session_id = bench_<case_id>，channel=benchmark，便于在 Langfuse 里过滤。
- 评分是"粗评"：点命中用关键词/字符重叠代理，仅供相对对比；权威质量判断请用 LLM judge / 人工评分。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 允许 `import eval.*`

from eval.forbidden_checker import check_forbidden

_PROD_HINTS = ("47.110.33.91", "shoujimama.cn", "aixzu.com")

# 判定“转人工/无法确认”的措辞（聚焦于“推诿/兜底”，尽量不误伤常规的“联系客服办理”）
_HANDOFF_MARKERS = [
    "转人工", "人工客服", "没查到", "没有查到", "查不到", "无法确认", "给不了",
    "以官方", "官方公示", "按平台规则", "建议以官方", "联系官方客服",
    "这我给不了", "没有准确", "我这边没有",
]


def load_golden(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                rows.append(json.loads(ln))
            except Exception as e:
                print(f"[warn] skip bad line: {e}", file=sys.stderr)
    return rows


def call_api(base_url: str, case: Dict[str, Any], timeout: int) -> Tuple[str, float, Optional[str]]:
    """POST /v1/qa。返回 (answer, latency_ms, error)。"""
    url = base_url.rstrip("/") + "/v1/qa"
    payload = {
        "question": case.get("question", ""),
        "session_id": f"bench_{case.get('id', 'na')}",
        "role": case.get("role", ""),
        "channel": "benchmark",
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
        dt = (time.perf_counter() - t0) * 1000
        try:
            obj = json.loads(body)
            answer = obj.get("answer", "") if isinstance(obj, dict) else ""
        except Exception:
            answer = body
        return answer, dt, None
    except urllib.error.HTTPError as e:
        dt = (time.perf_counter() - t0) * 1000
        return "", dt, f"HTTP {e.code}"
    except Exception as e:
        dt = (time.perf_counter() - t0) * 1000
        return "", dt, f"{type(e).__name__}: {e}"


def _tokens(point: str) -> List[str]:
    seps = "、，,。；;：: /（）()【】\n\t "
    buf, out = "", []
    for ch in point:
        if ch in seps:
            if len(buf) >= 2:
                out.append(buf)
            buf = ""
        else:
            buf += ch
    if len(buf) >= 2:
        out.append(buf)
    return out


def point_hit(point: str, answer: str) -> bool:
    """粗判一个标准答案要点是否被命中（关键词 / 字符重叠代理）。"""
    if not point or not answer:
        return False
    if point in answer:
        return True
    for tok in _tokens(point):
        if len(tok) >= 3 and tok in answer:
            return True
    chars = {c for c in point if "\u4e00" <= c <= "\u9fff"}
    if chars:
        ratio = sum(1 for c in chars if c in answer) / len(chars)
        if ratio >= 0.7:
            return True
    return False


def detect_handoff(answer: str) -> bool:
    return any(m in (answer or "") for m in _HANDOFF_MARKERS)


def required_sources_hit(required: List[str], answer: str) -> Tuple[int, int]:
    """粗代理：required_sources 关键词是否出现在答案里（真实 sources 只在 Langfuse）。"""
    if not required:
        return 0, 0
    hit = sum(1 for s in required if s and s in (answer or ""))
    return hit, len(required)


def rough_score(
    *,
    error: Optional[str],
    forbidden: Dict[str, Any],
    points_ratio: float,
    must_handoff: bool,
    handoff_detected: bool,
) -> float:
    if error:
        return 0.0
    if not forbidden.get("passed", True):
        return 0.0 if forbidden.get("severity") == "high" else min(2.0, 5 * points_ratio)
    base = 5.0 * points_ratio
    if must_handoff:
        return 5.0 if handoff_detected else min(base, 1.5)
    if handoff_detected:  # 不该转却转了，轻罚
        base = min(base, 3.0)
    return round(base, 1)


def fetch_retrieved_sources(session_id: str, cfg: Optional[Dict[str, str]]) -> Optional[List[str]]:
    """从 Langfuse 反查该 session 的 trace，取 metadata.sources（真实检索命中）。只读，失败返回 None。"""
    if not cfg:
        return None
    import base64
    host = cfg["host"].rstrip("/")
    url = f"{host}/api/public/traces?sessionId={session_id}&limit=1"
    token = base64.b64encode(f"{cfg['pk']}:{cfg['sk']}".encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {token}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", "ignore"))
        items = data.get("data") or []
        if not items:
            return None
        meta = items[0].get("metadata") or {}
        src = meta.get("sources")
        return [str(x) for x in src] if isinstance(src, list) else None
    except Exception:
        return None


def _langfuse_cfg(args: argparse.Namespace) -> Optional[Dict[str, str]]:
    if not getattr(args, "langfuse", False):
        return None
    import os
    host = args.langfuse_host or os.getenv("LANGFUSE_HOST", "")
    pk = args.langfuse_public_key or os.getenv("LANGFUSE_PUBLIC_KEY", "")
    sk = args.langfuse_secret_key or os.getenv("LANGFUSE_SECRET_KEY", "")
    if not (host and pk and sk):
        print("[warn] --langfuse 已开但缺 host/public/secret（可用 LANGFUSE_* 环境变量），跳过反查。",
              file=sys.stderr)
        return None
    return {"host": host, "pk": pk, "sk": sk}


def run(args: argparse.Namespace) -> Dict[str, Any]:
    golden = load_golden(Path(args.golden))
    if args.limit:
        golden = golden[: args.limit]

    use_judge = bool(args.use_judge)
    judge_fn = None
    if use_judge:
        try:
            from eval.judge import judge_case as judge_fn  # type: ignore
        except Exception as e:
            print(f"[warn] judge disabled (import failed): {e}", file=sys.stderr)
            use_judge = False

    lf_cfg = _langfuse_cfg(args)
    if lf_cfg:
        # 给异步入库留一点时间：跑完全部后统一反查（这里逐条即时反查，间隔小）
        pass

    results: List[Dict[str, Any]] = []
    for case in golden:
        answer, latency_ms, error = call_api(args.base_url, case, args.timeout)
        fb = check_forbidden(answer, case.get("forbidden_terms", []))
        pts = case.get("expected_answer_points", []) or []
        hit = sum(1 for p in pts if point_hit(p, answer))
        ratio = (hit / len(pts)) if pts else 0.0
        must_handoff = bool(case.get("must_handoff", False))
        handoff_detected = detect_handoff(answer)
        src_hit, src_total = required_sources_hit(case.get("required_sources", []), answer)
        score = rough_score(
            error=error, forbidden=fb, points_ratio=ratio,
            must_handoff=must_handoff, handoff_detected=handoff_detected,
        )
        rec: Dict[str, Any] = {
            "id": case.get("id"),
            "category": case.get("category"),
            "role": case.get("role"),
            "question": case.get("question"),
            "answer": answer,
            "latency_ms": round(latency_ms, 1),
            "forbidden_passed": fb["passed"],
            "forbidden_violations": fb["violations"],
            "forbidden_severity": fb["severity"],
            "must_handoff_expected": must_handoff,
            "must_handoff_detected": handoff_detected,
            "handoff_correct": must_handoff == handoff_detected,
            "expected_answer_points_hit_count": hit,
            "expected_answer_points_total": len(pts),
            "required_sources_hit": src_hit,
            "required_sources_total": src_total,
            "rough_score": score,
            "needs_business_review": bool(case.get("needs_business_review", False)),
            "error": error,
        }
        if use_judge and judge_fn and not error:
            rec["judge"] = judge_fn(case, answer)
        if lf_cfg and not error:
            real = fetch_retrieved_sources(f"bench_{case.get('id', 'na')}", lf_cfg)
            if real is not None:
                rec["retrieved_sources"] = real
                req = case.get("required_sources", []) or []
                joined = " ".join(real)
                rec["required_sources_real_hit"] = sum(1 for s in req if s and s in joined)
        results.append(rec)
        tag = "ERR" if error else ("RED" if not fb["passed"] else f"{score}")
        print(f"[{rec['id']}] {tag} pts {hit}/{len(pts)} {rec['latency_ms']}ms")

    return summarize(results, golden, args)


def summarize(results: List[Dict], golden: List[Dict], args: argparse.Namespace) -> Dict[str, Any]:
    total = len(results)
    errored = [r for r in results if r["error"]]
    ok = [r for r in results if not r["error"]]
    scores = [r["rough_score"] for r in ok]
    avg = round(sum(scores) / len(scores), 2) if scores else 0.0

    by_cat: Dict[str, List[float]] = {}
    for r in ok:
        by_cat.setdefault(r["category"], []).append(r["rough_score"])
    cat_avg = {c: round(sum(v) / len(v), 2) for c, v in by_cat.items()}

    red_fails = [r for r in results if not r["forbidden_passed"]]
    handoff_correct = sum(1 for r in results if r["handoff_correct"])
    handoff_acc = round(handoff_correct / total, 3) if total else 0.0
    pt_total = sum(r["expected_answer_points_total"] for r in results)
    pt_hit = sum(r["expected_answer_points_hit_count"] for r in results)
    pt_rate = round(pt_hit / pt_total, 3) if pt_total else 0.0
    worst = sorted(ok, key=lambda r: r["rough_score"])[:10]

    # LLM judge 聚合（仅当有 judge 结果）
    judged = [r["judge"] for r in results if isinstance(r.get("judge"), dict)]
    judge_summary: Dict[str, Any] = {}
    if judged:
        def _avg(key: str) -> float:
            vals = [j.get(key) for j in judged if isinstance(j.get(key), (int, float))]
            return round(sum(vals) / len(vals), 2) if vals else 0.0
        etypes: Dict[str, int] = {}
        for j in judged:
            et = str(j.get("error_type", "ok"))
            etypes[et] = etypes.get(et, 0) + 1
        judge_summary = {
            "judged_count": len(judged),
            "avg_correctness": _avg("correctness"),
            "avg_groundedness": _avg("groundedness"),
            "avg_helpfulness": _avg("helpfulness"),
            "compliance_pass_rate": round(
                sum(1 for j in judged if j.get("compliance") == 1) / len(judged), 3),
            "error_type_counts": etypes,
        }

    # Langfuse 真实来源反查聚合
    with_src = [r for r in results if isinstance(r.get("retrieved_sources"), list)]
    lf_summary: Dict[str, Any] = {}
    if with_src:
        rs_total = sum(r.get("required_sources_total", 0) for r in with_src)
        rs_hit = sum(r.get("required_sources_real_hit", 0) for r in with_src)
        lf_summary = {
            "cases_with_sources": len(with_src),
            "required_sources_real_hit_rate": round(rs_hit / rs_total, 3) if rs_total else 0.0,
        }

    return {
        "meta": {
            "golden": str(args.golden),
            "base_url": args.base_url,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "use_judge": bool(args.use_judge),
        },
        "summary": {
            "total": total,
            "ok": len(ok),
            "errored": len(errored),
            "avg_score": avg,
            "category_avg": cat_avg,
            "forbidden_violation_count": len(red_fails),
            "must_handoff_accuracy": handoff_acc,
            "answer_points_hit_rate": pt_rate,
        },
        "judge_summary": judge_summary,
        "langfuse_summary": lf_summary,
        "red_fails": [
            {"id": r["id"], "question": r["question"], "violations": r["forbidden_violations"]}
            for r in red_fails
        ],
        "worst10": [
            {"id": r["id"], "category": r["category"], "score": r["rough_score"], "question": r["question"]}
            for r in worst
        ],
        "results": results,
    }


def write_reports(report: Dict[str, Any], output_dir: Path) -> Tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"masanduo_benchmark_{ts}.json"
    md_path = output_dir / f"masanduo_benchmark_{ts}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    s = report["summary"]
    lines: List[str] = []
    lines.append(f"# 马三多 Benchmark 报告 {ts}")
    lines.append("")
    lines.append(f"- golden: `{report['meta']['golden']}`")
    lines.append(f"- base_url: `{report['meta']['base_url']}`")
    lines.append(f"- 生成时间: {report['meta']['generated_at']}")
    lines.append(f"- LLM judge: {'开' if report['meta']['use_judge'] else '关'}")
    lines.append("")
    lines.append("## 总览")
    lines.append("")
    lines.append(f"- 总题数: {s['total']}")
    lines.append(f"- 成功: {s['ok']}　报错: {s['errored']}")
    lines.append(f"- 平均分(0-5): **{s['avg_score']}**")
    lines.append(f"- 禁用词/红线违规数: **{s['forbidden_violation_count']}**")
    lines.append(f"- must_handoff 准确率: **{s['must_handoff_accuracy']}**")
    lines.append(f"- 标准答案要点平均命中率: **{s['answer_points_hit_rate']}**")
    js = report["summary"].get("judge_summary") or {}
    if js:
        lines.append("")
        lines.append("## LLM 裁判聚合")
        lines.append(f"- 评判题数: {js['judged_count']}")
        lines.append(f"- 平均 correctness: {js['avg_correctness']} / groundedness: {js['avg_groundedness']} / helpfulness: {js['avg_helpfulness']}")
        lines.append(f"- 合规通过率(compliance=1): {js['compliance_pass_rate']}")
        lines.append(f"- error_type 分布: {js['error_type_counts']}")
    lf = report["summary"].get("langfuse_summary") or {}
    if lf:
        lines.append("")
        lines.append("## Langfuse 真实检索来源")
        lines.append(f"- 有来源的题数: {lf['cases_with_sources']}")
        lines.append(f"- required_sources 真实命中率: {lf['required_sources_real_hit_rate']}")
    lines.append("")
    lines.append("## 各类别平均分")
    lines.append("")
    lines.append("| 类别 | 平均分 |")
    lines.append("|---|---|")
    for c, v in sorted(s["category_avg"].items(), key=lambda kv: kv[1]):
        lines.append(f"| {c} | {v} |")
    lines.append("")
    lines.append("## 红线/禁用词失败 case")
    lines.append("")
    if report["red_fails"]:
        lines.append("| id | 问题 | 命中禁用词 |")
        lines.append("|---|---|---|")
        for r in report["red_fails"]:
            terms = "、".join(str(v.get("term")) for v in r["violations"])
            lines.append(f"| {r['id']} | {r['question']} | {terms} |")
    else:
        lines.append("无 ✅")
    lines.append("")
    lines.append("## 最差 10 个 case")
    lines.append("")
    lines.append("| id | 类别 | 分数 | 问题 |")
    lines.append("|---|---|---|---|")
    for r in report["worst10"]:
        lines.append(f"| {r['id']} | {r['category']} | {r['score']} | {r['question']} |")
    lines.append("")
    lines.append("## 建议下一步")
    lines.append("")
    lines.append(_suggest(report))
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def _suggest(report: Dict[str, Any]) -> str:
    s = report["summary"]
    tips: List[str] = []
    if s["errored"]:
        tips.append(f"- 有 {s['errored']} 题请求报错：确认 API 是否在跑、base_url 是否正确。")
    if s["forbidden_violation_count"]:
        tips.append("- 存在红线/禁用词违规：**上线门槛要求为 0**，优先修 replies/router/prompt 或补红线词表。")
    low = [c for c, v in s["category_avg"].items() if v < 4]
    if low:
        tips.append(f"- 低于 4 分的类别：{'、'.join(low)}——优先补这些类别的知识库内容与路由。")
    if s["must_handoff_accuracy"] < 0.95:
        tips.append("- must_handoff 准确率未达 95%：检查'该转人工没转/不该转乱转'的 case。")
    if s["answer_points_hit_rate"] < 0.8:
        tips.append("- 要点命中率偏低：可能是知识库缺内容或检索没召回；结合 Langfuse 的 sources 排查。")
    tips.append("- 规则评分为粗评，建议开启 `--use-judge` 或人工在 Langfuse Annotation Queue 复核最差 10 题。")
    return "\n".join(tips)


def main() -> None:
    ap = argparse.ArgumentParser(description="马三多问答 benchmark runner")
    ap.add_argument("--golden", default="eval/golden_masanduo_v1.jsonl")
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--output-dir", default="eval/reports")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 题（0=全部）")
    ap.add_argument("--use-judge", action="store_true", help="启用 LLM-as-judge（需可用 LLM）")
    ap.add_argument("--langfuse", action="store_true", help="反查 Langfuse 取真实检索来源（只读）")
    ap.add_argument("--langfuse-host", default="", help="默认读环境变量 LANGFUSE_HOST")
    ap.add_argument("--langfuse-public-key", default="", help="默认读环境变量 LANGFUSE_PUBLIC_KEY")
    ap.add_argument("--langfuse-secret-key", default="", help="默认读环境变量 LANGFUSE_SECRET_KEY")
    ap.add_argument("--allow-prod", action="store_true", help="允许打生产地址（默认拒绝）")
    args = ap.parse_args()

    if any(h in args.base_url for h in _PROD_HINTS) and not args.allow_prod:
        print(
            f"[refused] base_url 疑似生产地址({args.base_url})。如确需对生产跑，请显式加 --allow-prod。",
            file=sys.stderr,
        )
        sys.exit(2)

    report = run(args)
    json_path, md_path = write_reports(report, Path(args.output_dir))
    print("\n=== 报告已生成 ===")
    print("JSON:", json_path)
    print("MD  :", md_path)
    s = report["summary"]
    print(
        f"总题 {s['total']} | 成功 {s['ok']} | 报错 {s['errored']} | "
        f"平均分 {s['avg_score']} | 红线违规 {s['forbidden_violation_count']} | "
        f"转人工准确率 {s['must_handoff_accuracy']}"
    )


if __name__ == "__main__":
    main()
