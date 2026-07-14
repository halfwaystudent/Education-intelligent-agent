from __future__ import annotations

import argparse
import html
import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.rag.loaders import load_text_pages
from app.rag.splitter import QuestionExtractor, build_chunk


REPORT_DIR = Path("data/english_splitter_reports")


def _safe_name(path: Path) -> str:
    return path.stem.replace("/", "_").replace("\\", "_")


def _json_value(value):
    if isinstance(value, Path):
        return str(value)
    return value


def _stats(chunks: list[dict]) -> dict:
    flags = Counter(flag for chunk in chunks for flag in chunk.get("quality_flags", []))
    types = Counter(chunk.get("question_type") or "unknown" for chunk in chunks)
    return {
        "chunks": len(chunks),
        "question_types": dict(types),
        "quality_flags": dict(flags),
        "with_material": sum(bool(chunk.get("material_id")) for chunk in chunks),
        "with_answer": sum(bool(chunk.get("answer")) for chunk in chunks),
        "with_analysis": sum(bool(chunk.get("analysis")) for chunk in chunks),
    }


def _render_report(source: Path, chunks: list[dict], stats: dict) -> str:
    cards = []
    for index, chunk in enumerate(chunks, 1):
        flags = chunk.get("quality_flags") or []
        flags_html = "".join(f'<span class="flag">{html.escape(flag)}</span>' for flag in flags)
        if not flags_html:
            flags_html = '<span class="ok">ok</span>'
        cards.append(f'''<article class="card">
<header><h2>#{index} · {html.escape(str(chunk.get("question_no") or ""))} · {html.escape(str(chunk.get("question_type") or ""))}</h2>
<div class="meta">{html.escape(str(chunk.get("section_title") or ""))}</div><div>{flags_html}</div></header>
<div class="display">{chunk.get("display_html") or html.escape(chunk.get("content") or "")}</div>
<details><summary>Embedding 文本</summary><pre>{html.escape(chunk.get("embedding_text") or "")}</pre></details>
<details><summary>结构化字段</summary><pre>{html.escape(json.dumps({k: chunk.get(k) for k in ("material_id", "match_method", "match_confidence", "image_paths")}, ensure_ascii=False, indent=2))}</pre></details>
</article>''')
    stats_html = html.escape(json.dumps(stats, ensure_ascii=False, indent=2))
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>{html.escape(source.name)}</title>
<style>body{{font-family:"Microsoft YaHei",sans-serif;margin:24px;background:#f5f6f8;color:#202124}}a{{color:#075ea8}}.card{{background:#fff;border:1px solid #d9dde3;border-radius:8px;padding:18px;margin:16px 0}}h2{{font-size:18px;margin:0 0 8px}}.meta{{color:#59636e;margin-bottom:8px}}.flag,.ok{{display:inline-block;padding:2px 7px;margin:2px;border-radius:4px;font-size:12px}}.flag{{background:#fff0c2;color:#704b00}}.ok{{background:#dff5e5;color:#166534}}.display{{line-height:1.75;margin-top:14px}}section{{border-left:3px solid #d6dbe1;padding-left:12px;margin:12px 0}}section h4{{margin:0 0 5px}}pre{{white-space:pre-wrap;word-break:break-word;background:#f3f4f6;padding:12px}}img{{max-width:100%;max-height:520px}}</style></head><body>
<h1>英语切分检查</h1><p>{html.escape(str(source))}</p><pre>{stats_html}</pre>{''.join(cards)}</body></html>'''


def process_file(source: Path, output_dir: Path) -> dict:
    pages = load_text_pages(source)
    extractor = QuestionExtractor(pages, subject="英语")
    questions = extractor.extract()
    chunks = [build_chunk(question) for question in questions]
    stats = _stats(chunks)
    stem = _safe_name(source)
    jsonl_path = output_dir / f"{stem}.jsonl"
    html_path = output_dir / f"{stem}.html"
    with jsonl_path.open("w", encoding="utf-8") as stream:
        for chunk in chunks:
            stream.write(json.dumps(chunk, ensure_ascii=False, default=_json_value) + "\n")
    html_path.write_text(_render_report(source, chunks, stats), encoding="utf-8")
    return {"file": source.name, "report": html_path.name, "jsonl": jsonl_path.name, **stats}


def _render_index(results: list[dict]) -> str:
    rows = []
    for result in results:
        severe = sum(result["quality_flags"].get(flag, 0) for flag in ("missing_stem", "missing_answer", "answer_count_mismatch", "missing_material"))
        rows.append(f'<tr><td><a href="{html.escape(result["report"])}">{html.escape(result["file"])}</a></td><td>{result["chunks"]}</td><td>{result["with_material"]}</td><td>{result["with_answer"]}</td><td>{severe}</td><td><a href="{html.escape(result["jsonl"])}">JSONL</a></td></tr>')
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>英语切分总览</title><style>body{{font-family:"Microsoft YaHei",sans-serif;margin:24px}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ccd1d7;padding:9px;text-align:left}}th{{background:#f1f3f5}}a{{color:#075ea8}}</style></head><body><h1>英语切分总览</h1><table><thead><tr><th>试卷</th><th>块数</th><th>含材料</th><th>含答案</th><th>关键告警</th><th>数据</th></tr></thead><tbody>{''.join(rows)}</tbody></table></body></html>'''


def main() -> None:
    parser = argparse.ArgumentParser(description="生成英语试卷切分验收报告，不写入向量库")
    parser.add_argument("--file", type=Path, help="只检查指定试卷")
    parser.add_argument("--input-dir", type=Path, default=Path("data/uploads/English"))
    parser.add_argument("--output-dir", type=Path, default=REPORT_DIR)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    files = [args.file] if args.file else sorted(args.input_dir.glob("*.docx"))
    results = [process_file(source, args.output_dir) for source in files]
    index_path = args.output_dir / "index.html"
    index_path.write_text(_render_index(results), encoding="utf-8")
    (args.output_dir / "summary.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"reports={len(results)}")
    print(f"index={index_path}")


if __name__ == "__main__":
    main()
