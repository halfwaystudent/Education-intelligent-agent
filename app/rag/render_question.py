from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path

from app.core.config import get_settings
from app.rag.image_ocr import image_to_text


_IMAGE_RX = re.compile(r"\[IMAGE_\d+(?::([^\]]+))?\]")
_CACHE_NAME = "question_ocr_cache.json"
_MIN_VISUAL_OCR_CHARS = 8


def _needs_visual_ocr(chunk: dict) -> bool:
    settings = get_settings()
    if not settings.question_render_ocr_enabled:
        return False
    if not settings.question_render_ocr_image_only:
        return True
    raw = " ".join(
        str(chunk.get(key) or "")
        for key in ("stem", "content", "raw_text", "analysis", "answer")
    )
    return bool(chunk.get("image_paths") or chunk.get("formulas") or "[IMAGE_" in raw or "[FORMULA:" in raw)


def enrich_chunks_with_visual_ocr(chunks: list[dict]) -> list[dict]:
    if not any(_needs_visual_ocr(chunk) for chunk in chunks):
        return chunks

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            return [
                _enrich_chunk_with_visual_ocr(chunk, browser) if _needs_visual_ocr(chunk) else chunk
                for chunk in chunks
            ]
        finally:
            browser.close()


def enrich_chunk_with_visual_ocr(chunk: dict) -> dict:
    if not _needs_visual_ocr(chunk):
        return chunk

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            return _enrich_chunk_with_visual_ocr(chunk, browser)
        finally:
            browser.close()


def _enrich_chunk_with_visual_ocr(chunk: dict, browser) -> dict:

    fallback = chunk.get("embedding_text") or chunk.get("content") or ""
    try:
        html_text = build_question_html(chunk)
        cache_key = _cache_key(html_text, chunk.get("image_paths") or [])
        image_path = render_question_image(html_text, cache_key, browser=browser)
        visual_text = _cached_visual_ocr(image_path, cache_key)
    except Exception as exc:
        chunk.setdefault("quality_flags", [])
        if "visual_ocr_failed" not in chunk["quality_flags"]:
            chunk["quality_flags"].append("visual_ocr_failed")
        chunk["visual_ocr_error"] = str(exc)
        return chunk

    chunk["question_image_path"] = str(image_path)
    chunk["question_image_url"] = f"/media/questions/{image_path.name}"
    chunk["visual_ocr_text"] = visual_text
    if len(visual_text.strip()) >= _MIN_VISUAL_OCR_CHARS:
        chunk["embedding_text"] = _embedding_text_from_visual_clean(chunk, visual_text, fallback)
    else:
        chunk["embedding_text"] = fallback
        chunk.setdefault("quality_flags", [])
        if "visual_ocr_short" not in chunk["quality_flags"]:
            chunk["quality_flags"].append("visual_ocr_short")
    return chunk


def build_question_html(chunk: dict) -> str:
    return _build_question_html_clean(chunk)
    title = _line("题型", chunk.get("question_type")) + _line("题号", chunk.get("question_no"))
    material = str(chunk.get("material_excerpt") or "")[:1800]
    sections = [
        _section("材料", material),
        _section("题干", chunk.get("stem")),
        _options_section(chunk.get("options") or []),
        _section("答案", chunk.get("answer")),
        _section("解析", chunk.get("analysis")),
        _section("点评", chunk.get("comment")),
    ]
    body = "".join(part for part in sections if part)
    if not body:
        body = _section("内容", chunk.get("content") or chunk.get("raw_text") or "")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: #ffffff; color: #111827; font-family: "Microsoft YaHei", "Noto Sans CJK SC", Arial, sans-serif; }}
.page {{ width: 920px; padding: 28px 32px; background: #fff; }}
.meta {{ margin-bottom: 14px; color: #4b5563; font-size: 18px; line-height: 1.7; }}
.meta span {{ margin-right: 22px; }}
section {{ margin: 18px 0; }}
h2 {{ margin: 0 0 8px; font-size: 22px; line-height: 1.35; color: #111827; font-weight: 700; }}
.text, .option {{ font-size: 22px; line-height: 1.9; white-space: normal; word-break: break-word; }}
.option {{ margin: 8px 0; }}
img.formula-img {{ max-width: 100%; max-height: 92px; vertical-align: middle; margin: 0 4px; }}
.formula-missing {{ display: inline-block; padding: 0 6px; color: #6b7280; border-bottom: 1px solid #d1d5db; }}
</style>
</head>
<body><main class="page"><div class="meta">{title}</div>{body}</main></body>
</html>"""


def render_question_image(html_text: str, cache_key: str, browser=None) -> Path:
    settings = get_settings()
    out_dir = settings.question_render_dir / "images"
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / f"{cache_key}.png"
    if output.exists():
        return output

    if browser is not None:
        page = browser.new_page(
            viewport={"width": settings.question_render_width, "height": 1200},
            device_scale_factor=max(settings.question_render_dpi_scale, 1),
        )
        try:
            page.set_content(html_text, wait_until="load")
            page.locator("main.page").screenshot(path=str(output))
        finally:
            page.close()
        return output

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            return render_question_image(html_text, cache_key, browser=browser)
        finally:
            browser.close()
    return output


def _cached_visual_ocr(image_path: Path, cache_key: str) -> str:
    cache_path = get_settings().question_render_dir / _CACHE_NAME
    cache = _load_json(cache_path)
    if cache_key in cache:
        return str(cache[cache_key])
    text = image_to_text(image_path)
    cache[cache_key] = text
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    return text


def _embedding_text_from_visual(chunk: dict, visual_text: str) -> str:
    return _embedding_text_from_visual_clean(chunk, visual_text)
    parts = [
        f"栏目：{chunk.get('section_title') or ''}",
        f"题型：{chunk.get('question_type') or ''}",
        f"题号：{chunk.get('question_no') or ''}",
        visual_text.strip(),
    ]
    answer = (chunk.get("answer") or "").strip()
    if answer:
        parts.append(f"答案：{answer}")
    return "\n".join(part for part in parts if part.strip())


def _section(title: str, text: str | None) -> str:
    if not text:
        return ""
    return f'<section><h2>{html.escape(title)}</h2><div class="text">{_render_inline(text)}</div></section>'


def _options_section(options: list[str]) -> str:
    if not options:
        return ""
    rendered = "".join(f'<div class="option">{_render_inline(option)}</div>' for option in options)
    return f"<section><h2>选项</h2>{rendered}</section>"
    if not options:
        return ""
    rendered = "".join(f'<div class="option">{_render_inline(option)}</div>' for option in options)
    return f"<section><h2>选项</h2>{rendered}</section>"


def _render_inline(text: str) -> str:
    parts: list[str] = []
    cursor = 0
    for match in _IMAGE_RX.finditer(text or ""):
        parts.append(html.escape(text[cursor:match.start()]).replace("\n", "<br>\n"))
        image_path = match.group(1)
        if image_path:
            rendered_path = _prepare_embedded_image(Path(image_path.strip()))
            if rendered_path:
                src = rendered_path.resolve().as_uri()
                parts.append(f'<img class="formula-img" src="{html.escape(src)}" alt="formula">')
            else:
                parts.append('<span class="formula-missing">[公式]</span>')
        else:
            parts.append('<span class="formula-missing">[图片]</span>')
        cursor = match.end()
    parts.append(html.escape(text[cursor:]).replace("\n", "<br>\n"))
    return "".join(parts)


def _prepare_embedded_image(path: Path) -> Path | None:
    if not path.exists():
        return None
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}:
        return path
    try:
        from app.rag.image_ocr import prepare_image_for_display

        return prepare_image_for_display(path)
    except Exception:
        return None


def _cache_key(html_text: str, image_paths: list[str]) -> str:
    digest = hashlib.sha256()
    digest.update(html_text.encode("utf-8", errors="ignore"))
    for raw_path in image_paths:
        path = Path(raw_path)
        digest.update(str(path).encode("utf-8", errors="ignore"))
        if path.exists():
            stat = path.stat()
            digest.update(str(stat.st_mtime_ns).encode())
            digest.update(str(stat.st_size).encode())
    return digest.hexdigest()[:24]


def _line(label: str, value: str | None) -> str:
    if not value:
        return ""
    return f"<span>{html.escape(label)}：{html.escape(str(value))}</span>"
    return f"<span>{html.escape(label)}：{html.escape(str(value))}</span>"


def _load_json(path: Path) -> dict[str, str]:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _build_question_html_clean(chunk: dict) -> str:
    title = _line("题型", chunk.get("question_type")) + _line("题号", chunk.get("question_no"))
    sections = [
        _section("题干", chunk.get("stem")),
        _options_section(chunk.get("options") or []),
        _section("答案", chunk.get("answer")),
        _section("解析", chunk.get("analysis")),
        _section("点评", chunk.get("comment")),
    ]
    body = "".join(part for part in sections if part)
    if not body:
        body = _section("内容", chunk.get("content") or chunk.get("raw_text") or "")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: #ffffff; color: #111827; font-family: "Microsoft YaHei", "Noto Sans CJK SC", Arial, sans-serif; }}
.page {{ width: 920px; padding: 28px 32px; background: #fff; }}
.meta {{ margin-bottom: 14px; color: #4b5563; font-size: 18px; line-height: 1.7; }}
.meta span {{ margin-right: 22px; }}
section {{ margin: 18px 0; }}
h2 {{ margin: 0 0 8px; font-size: 22px; line-height: 1.35; color: #111827; font-weight: 700; }}
.text, .option {{ font-size: 22px; line-height: 1.9; white-space: normal; word-break: break-word; }}
.option {{ margin: 8px 0; }}
img.formula-img {{ max-width: 100%; max-height: 92px; vertical-align: middle; margin: 0 4px; }}
.formula-missing {{ display: inline-block; padding: 0 6px; color: #6b7280; border-bottom: 1px solid #d1d5db; }}
</style>
</head>
<body><main class="page"><div class="meta">{title}</div>{body}</main></body>
</html>"""


def _embedding_text_from_visual_clean(chunk: dict, visual_text: str, fallback: str = "") -> str:
    from app.storage.vectorstore import sanitize_embedding_text

    base = sanitize_embedding_text(fallback, max_chars=4200)
    visual = sanitize_embedding_text(visual_text, max_chars=1600)
    parts = [base]
    if visual:
        parts.append(f"视觉OCR：{visual}")
    return "\n".join(part for part in parts if part.strip())
