from __future__ import annotations

import argparse
import html
from collections import Counter
from pathlib import Path

from app.rag.loaders import load_text_pages
from app.rag.splitter import QuestionExtractor, build_chunk, split_documents


def find_default_file() -> Path:
    patterns = [
        "data/uploads/Chinese/*2024*全国甲卷*解析卷*.docx",
        "data/uploads/Chinese/*2023*上海*秋考*答案卷*.docx",
        "data/uploads/Chinese/*.docx",
        "data/uploads/Math/*2024*新高考Ⅰ卷*解析卷*.docx",
        "data/uploads/Math/*2024*新高考*Ⅰ*解析卷*.docx",
        "data/uploads/Math/*2024*北京*解析卷*.docx",
        "data/uploads/Math/*.docx",
    ]
    for pattern in patterns:
        files = sorted(Path().glob(pattern))
        if files:
            return files[0]
    raise FileNotFoundError("未找到可测试的 docx 文件")


def preview(text: str, limit: int = 180) -> str:
    text = " ".join((text or "").split())
    return text[:limit] + ("..." if len(text) > limit else "")


def build_html_report(file_path: Path, chunks: list[dict], stats: dict) -> str:
    cards = []
    for index, chunk in enumerate(chunks, 1):
        flags = chunk.get("quality_flags") or []
        flag_html = "".join(f'<span class="flag">{html.escape(flag)}</span>' for flag in flags) or '<span class="ok">ok</span>'
        image_paths = chunk.get("image_paths") or []
        image_links = "".join(
            f'<li><a href="../{html.escape(path)}">{html.escape(Path(path).name)}</a></li>'
            for path in image_paths[:20]
        )
        if len(image_paths) > 20:
            image_links += f'<li>... 共 {len(image_paths)} 张</li>'
        cards.append(
            f'''
            <article class="card">
              <header>
                <h2>#{index} 题号 {html.escape(str(chunk.get('question_no') or ''))} · {html.escape(str(chunk.get('question_type') or ''))}</h2>
                <div class="meta">栏目：{html.escape(str(chunk.get('section_title') or ''))}</div>
                <div class="flags">{flag_html}</div>
              </header>
              <div class="display">{chunk.get('display_html') or html.escape(chunk.get('content') or '')}</div>
              <details>
                <summary>Embedding 文本</summary>
                <pre>{html.escape(chunk.get('embedding_text') or '')}</pre>
              </details>
              <details>
                <summary>图片路径 ({len(image_paths)})</summary>
                <ul>{image_links}</ul>
              </details>
            </article>
            '''
        )
    stats_html = "".join(f"<li><b>{html.escape(str(k))}</b>: {html.escape(str(v))}</li>" for k, v in stats.items())
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>Splitter Report</title>
<style>
body {{ font-family: 'Microsoft YaHei', system-ui, sans-serif; margin: 24px; background: #f6f7f9; color: #222; }}
.card {{ background: white; border: 1px solid #ddd; border-radius: 10px; padding: 18px; margin: 16px 0; box-shadow: 0 1px 4px #0001; }}
h1 {{ margin-bottom: 4px; }}
h2 {{ margin: 0 0 8px; font-size: 18px; }}
.meta {{ color: #666; font-size: 13px; margin-bottom: 8px; }}
.flag {{ display: inline-block; background: #fff3cd; color: #8a5a00; border: 1px solid #ffe08a; border-radius: 999px; padding: 2px 8px; margin: 2px; font-size: 12px; }}
.ok {{ display: inline-block; background: #e7f8ed; color: #137333; border-radius: 999px; padding: 2px 8px; font-size: 12px; }}
.display {{ color: #111; font-family: 'Times New Roman', 'SimSun', 'STSong', serif; line-height: 2; font-size: 18px; }}
.formula-img {{ width: auto; height: auto; max-width: 100%; max-height: 64px; vertical-align: -0.28em; margin: 0 3px; background: white; }}
.formula-link {{ display: inline-block; padding: 1px 5px; margin: 0 2px; border: 1px solid #bbb; border-radius: 4px; background: #fafafa; color: #0645ad; text-decoration: none; }}
pre {{ white-space: pre-wrap; background: #f4f4f4; padding: 10px; border-radius: 6px; }}
details {{ margin-top: 10px; }}
</style>
</head>
<body>
<h1>Splitter Report</h1>
<p>文件：{html.escape(str(file_path))}</p>
<ul>{stats_html}</ul>
{''.join(cards)}
</body>
</html>'''


def main() -> None:
    parser = argparse.ArgumentParser(description="检查试卷题目抽取效果")
    parser.add_argument("--file", type=Path, default=None, help="要测试的 PDF/DOCX/TXT 文件")
    parser.add_argument("--mode", choices=["summary", "detail", "raw"], default="summary")
    parser.add_argument("--limit", type=int, default=0, help="最多打印多少题，0 表示全部")
    parser.add_argument("--subject", default="", help="subject override; inferred from upload directory by default")
    args = parser.parse_args()

    report_lines: list[str] = []

    def emit(*values):
        line = " ".join(str(v) for v in values)
        print(line)
        report_lines.append(line)

    file_path = args.file or find_default_file()
    emit("file exists:", file_path.exists())
    emit("file:", file_path)

    emit("loading pages...")
    pages = load_text_pages(file_path)
    subject = args.subject.strip()
    if not subject:
        path_parts = {part.lower() for part in file_path.parts}
        if "math" in path_parts:
            subject = "\u6570\u5b66"
        elif "english" in path_parts:
            subject = "\u82f1\u8bed"
        elif "chinese" in path_parts:
            subject = "\u8bed\u6587"
    emit("subject:", subject or "auto")
    emit("pages:", len(pages))
    emit("text chars:", sum(len(p.get("text", "")) for p in pages))

    extractor = QuestionExtractor(pages, subject=subject)
    questions = extractor.extract()
    if questions and subject == "??":
        from app.rag.image_ocr import prepare_images_for_display

        prepare_images_for_display(
            [image_path for question in questions for image_path in question.image_paths]
        )
    chunks = [build_chunk(question) for question in questions] if questions else split_documents(pages, subject=subject)

    quality_counter = Counter(flag for chunk in chunks for flag in (chunk.get("quality_flags") or []))
    type_counter = Counter(chunk.get("question_type") or "unknown" for chunk in chunks)
    image_count = sum(len(chunk.get("image_paths") or []) for chunk in chunks)
    option_counts = Counter(len(chunk.get("options") or []) for chunk in chunks)
    matched_count = sum(1 for chunk in chunks if chunk.get("match_method"))
    low_confidence_count = sum(
        1
        for chunk in chunks
        if chunk.get("match_method") and float(chunk.get("match_confidence") or 0) < 0.9
    )
    unmatched_answer_count = sum(1 for chunk in chunks if chunk.get("chunk_type") == "unmatched_answer")
    composition_count = sum(1 for chunk in chunks if chunk.get("is_composition"))

    emit("sections:", len(extractor.sections))
    for i, section in enumerate(extractor.sections, 1):
        emit(f"  section {i}: {section.title or '[no title]'} chars={len(section.text)}")
    emit("question_blocks:", len(extractor.blocks))
    emit("questions/chunks:", len(chunks))
    emit("question_type_stats:", dict(type_counter))
    emit("quality_flag_stats:", dict(quality_counter))
    emit("option_count_stats:", dict(option_counts))
    emit("image_refs:", image_count)
    emit("materials:", len(getattr(extractor, "materials", [])))
    emit("answer_blocks:", len(getattr(extractor, "answers", [])))
    emit("matched_questions:", matched_count)
    emit("low_confidence_matches:", low_confidence_count)
    emit("unmatched_answers:", unmatched_answer_count)
    emit("compositions:", composition_count)
    emit("layout_type:", getattr(extractor, "layout_type", ""))

    printed = 0
    for index, chunk in enumerate(chunks, 1):
        if args.limit and printed >= args.limit:
            break
        printed += 1
        flags = chunk.get("quality_flags") or []
        options = chunk.get("options") or []
        images = chunk.get("image_paths") or []
        emit("=" * 80)
        emit(f"#{index} Q{chunk.get('question_no')} {chunk.get('question_type')} chunk={chunk.get('chunk_type')} flags={','.join(flags) or '-'}")
        emit("section:", chunk.get("section_title"))
        emit("stem:", preview(chunk.get("content") or "", 260))
        emit("options_count:", len(options), "answer:", chunk.get("answer") or "")
        if images:
            emit("images:", len(images), preview("; ".join(images), 260))

        if args.mode == "detail":
            emit("[STEM]")
            emit(chunk.get("stem") or "")
            emit("[OPTIONS]")
            for option in options:
                emit(option)
            emit("[ANSWER]")
            emit(chunk.get("answer") or "")
            emit("[ANALYSIS]")
            emit(preview(chunk.get("analysis") or "", 2000))
            emit("[COMMENT]")
            emit(chunk.get("comment") or "")
        elif args.mode == "raw":
            emit("[RAW]")
            emit((chunk.get("raw_text") or chunk.get("content") or "")[:2500])

    stats = {
        "sections": len(extractor.sections),
        "question_blocks": len(extractor.blocks),
        "questions": len(chunks),
        "question_type_stats": dict(type_counter),
        "quality_flag_stats": dict(quality_counter),
        "option_count_stats": dict(option_counts),
        "image_refs": image_count,
        "materials": len(getattr(extractor, "materials", [])),
        "answer_blocks": len(getattr(extractor, "answers", [])),
        "matched_questions": matched_count,
        "low_confidence_matches": low_confidence_count,
        "unmatched_answers": unmatched_answer_count,
        "compositions": composition_count,
        "layout_type": getattr(extractor, "layout_type", ""),
    }
    txt_path = Path("data/splitter_report.txt")
    txt_path.parent.mkdir(parents=True, exist_ok=True)
    txt_path.write_text("\n".join(report_lines), encoding="utf-8")
    html_path = Path("data/splitter_report.html")
    html_path.write_text(build_html_report(file_path, chunks, stats), encoding="utf-8")
    print("report_txt:", txt_path)
    print("report_html:", html_path)


if __name__ == "__main__":
    main()
