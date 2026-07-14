from __future__ import annotations

import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path


class OCRError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def get_ocr_engine():
    try:
        from rapidocr import RapidOCR
    except ImportError as exc:
        raise OCRError("缺少 OCR 依赖 rapidocr，请先执行：pip install -r requirements.txt") from exc
    return RapidOCR()


def find_pdftoppm() -> str:
    executable = shutil.which("pdftoppm.exe") or shutil.which("pdftoppm") or shutil.which("pdftoppm.cmd")
    candidates: list[Path] = []
    if executable:
        exe_path = Path(executable)
        candidates.append(exe_path)
        candidates.extend(
            [
                exe_path.parent / "pdftoppm.exe",
                exe_path.parent.parent / "native" / "poppler" / "Library" / "bin" / "pdftoppm.exe",
                exe_path.parent / "Library" / "bin" / "pdftoppm.exe",
                exe_path.parent.parent / "Library" / "bin" / "pdftoppm.exe",
                exe_path.parent.parent.parent / "native" / "poppler" / "Library" / "bin" / "pdftoppm.exe",
                exe_path.parent.parent.parent / "Library" / "bin" / "pdftoppm.exe",
            ]
        )
    for candidate in candidates:
        if candidate.exists() and candidate.suffix.lower() == ".exe":
            return str(candidate)
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    raise OCRError("缺少 PDF 渲染工具 pdftoppm，请安装 Poppler 或确认 pdftoppm 已在 PATH 中。")


def ocr_pdf_pages(path: Path, page_numbers: list[int] | None = None, dpi: int = 240) -> list[dict]:
    if page_numbers is not None and not page_numbers:
        return []

    pdftoppm = find_pdftoppm()
    engine = get_ocr_engine()
    with tempfile.TemporaryDirectory(prefix="edu_ocr_") as temp_dir:
        output_prefix = Path(temp_dir) / "page"
        command = [pdftoppm, "-png", "-r", str(dpi)]
        if page_numbers is not None:
            command.extend(["-f", str(min(page_numbers)), "-l", str(max(page_numbers))])
        command.extend([str(path), str(output_prefix)])
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "unknown error").strip()
            raise OCRError(f"PDF 页面渲染失败：{detail}")

        image_paths = sorted(Path(temp_dir).glob("page-*.png"))
        if not image_paths:
            raise OCRError("PDF 页面渲染后没有生成图片，无法 OCR。")

        rendered_start = min(page_numbers) if page_numbers is not None else 1
        wanted = set(page_numbers) if page_numbers is not None else None
        pages: list[dict] = []
        for offset, image_path in enumerate(image_paths):
            page_number = rendered_start + offset
            if wanted is not None and page_number not in wanted:
                continue
            text = ocr_image(image_path, engine)
            pages.append({"text": text, "page": page_number})

    if not any(page["text"].strip() for page in pages):
        raise OCRError("OCR 未识别出有效文本，可能是图片质量过低或页面不含文字。")
    return pages


def ocr_image(image_path: Path, engine) -> str:
    output = engine(str(image_path))
    if hasattr(output, "txts"):
        return "\n".join(str(text).strip() for text in output.txts if str(text).strip())

    if isinstance(output, tuple):
        result = output[0]
    else:
        result = output
    if not result:
        return ""

    lines = []
    for item in result:
        if len(item) >= 2 and item[1]:
            lines.append(str(item[1]).strip())
    return "\n".join(line for line in lines if line)
