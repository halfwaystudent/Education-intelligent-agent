
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote


CACHE_PATH = Path("data/image_ocr_cache.json")
DISPLAY_IMAGE_DIR = Path("data/image_ocr_rendered")
DISPLAY_IMAGE_URL_PREFIX = "/media/formulas"
_VECTOR_SUFFIXES = {".wmf", ".emf"}
_RASTER_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
_OFFICE_VECTOR_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "export_office_vectors.ps1"


@lru_cache(maxsize=1)
def _get_engine():
    from rapidocr import RapidOCR

    return RapidOCR()


def _load_cache() -> dict[str, str]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache: dict[str, str]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def image_to_text(image_path: str | Path) -> str:
    path = Path(image_path)
    if not path.exists():
        return ""
    key = str(path.resolve())
    cache = _load_cache()
    if key in cache:
        return _fix_mojibake(cache[key])

    try:
        prepared = _prepare_image(path)
        output = _get_engine()(str(prepared))
        text = _fix_mojibake(_rapidocr_text(output))
    except Exception:
        text = ""

    cache[key] = text
    _save_cache(cache)
    return text


def _prepare_image(path: Path) -> Path:
    from PIL import Image, ImageOps

    out_dir = DISPLAY_IMAGE_DIR / path.parent.name
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / f"{path.stem}.display.png"
    if output.exists():
        return output

    with Image.open(path) as image:
        image = image.convert("RGB")
        width, height = image.size
        longest = max(width, height, 1)
        if longest > 1600:
            scale = 1600 / longest
        else:
            scale = max(1.0, min(4.0, 600 / longest))
        image = image.resize(
            (max(int(width * scale), 80), max(int(height * scale), 40)),
            resample=Image.Resampling.LANCZOS,
        )
        image = ImageOps.expand(image, border=8, fill="white")
        image.save(output)
    return output


def prepare_images_for_display(image_paths: list[str | Path]) -> dict[str, Path]:
    """Prepare display assets in bounded Office batches so formulas stay sharp."""
    paths = list(dict.fromkeys(Path(path) for path in image_paths if Path(path).exists()))
    vector_paths = [path for path in paths if path.suffix.lower() in _VECTOR_SUFFIXES]
    _export_office_vectors(vector_paths)

    results: dict[str, Path] = {}
    for path in paths:
        office_output = DISPLAY_IMAGE_DIR / path.parent.name / f"{path.stem}.office.png"
        if path.suffix.lower() in _VECTOR_SUFFIXES and office_output.exists():
            results[str(path)] = office_output
        else:
            results[str(path)] = _prepare_image(path)
    return results


def _export_office_vectors(paths: list[Path]) -> None:
    if os.name != "nt" or not paths or not _OFFICE_VECTOR_SCRIPT.exists():
        return

    items = []
    for path in dict.fromkeys(path.resolve() for path in paths):
        output = DISPLAY_IMAGE_DIR / path.parent.name / f"{path.stem}.office.png"
        if output.exists():
            continue
        output.parent.mkdir(parents=True, exist_ok=True)
        items.append({"source": str(path), "output": str(output.resolve())})
    if not items:
        return

    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        return

    # Restart PowerPoint periodically. Large DOCX files can contain hundreds of
    # MathType previews, and one huge COM session becomes progressively slower.
    batch_size = 40
    for offset in range(0, len(items), batch_size):
        batch = items[offset : offset + batch_size]
        manifest_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as manifest:
                json.dump(batch, manifest, ensure_ascii=False)
                manifest_path = Path(manifest.name)
            subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(_OFFICE_VECTOR_SCRIPT),
                    "-ManifestPath",
                    str(manifest_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError):
            # Any failed batch falls back to Pillow below; indexing still completes.
            continue
        finally:
            if manifest_path:
                manifest_path.unlink(missing_ok=True)


def _rapidocr_text(output) -> str:
    if hasattr(output, "txts"):
        return " ".join(str(text).strip() for text in output.txts if str(text).strip())
    result = output[0] if isinstance(output, tuple) else output
    if not result:
        return ""
    lines: list[str] = []
    for item in result:
        if len(item) >= 2 and item[1]:
            lines.append(str(item[1]).strip())
    return " ".join(lines)


def _fix_mojibake(text: str) -> str:
    if not text:
        return ""
    markers = ("锛", "棰", "€", "绛", "瑙", "析", "瀷")
    if not any(marker in text for marker in markers):
        return text
    try:
        repaired = text.encode("gb18030", errors="strict").decode("utf-8", errors="strict")
    except Exception:
        return text
    return repaired if _cjk_count(repaired) >= _cjk_count(text) else text


def _cjk_count(text: str) -> int:
    return sum(1 for char in text if "\u4e00" <= char <= "\u9fff")


def _office_render_path(path: Path) -> Path | None:
    if path.suffix.lower() not in _VECTOR_SUFFIXES:
        return None
    return DISPLAY_IMAGE_DIR / path.parent.name / f"{path.stem}.office.png"


def prepare_image_for_display(image_path: str | Path) -> Path:
    """Convert DOCX images into browser-safe assets using high-resolution Office rendering."""
    path = Path(image_path)
    output = _office_render_path(path)
    if output is not None:
        if not output.exists():
            _export_office_vectors([path])
        if output.exists():
            return output
    return _prepare_image(path)


def display_image_url(image_path: str | Path) -> str:
    path = Path(image_path).resolve()
    root = DISPLAY_IMAGE_DIR.resolve()
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        return ""
    return f"{DISPLAY_IMAGE_URL_PREFIX}/{quote(relative, safe='/')}"
