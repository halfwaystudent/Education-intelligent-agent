
from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile



MIN_EXTRACTED_CHARS = 50
SCAN_SAMPLE_PAGES = 5
_NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "v": "urn:schemas-microsoft-com:vml",
}


def load_text_pages(path: Path) -> list[dict]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _load_pdf(path)
    if suffix == ".docx":
        return _load_docx(path)
    if suffix in {".txt", ".md", ".markdown"}:
        return [{"text": path.read_text(encoding="utf-8-sig", errors="ignore"), "page": None}]
    raise ValueError(f"??????????{suffix}")


def _load_pdf(path: Path) -> list[dict]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        pages.append({"text": page.extract_text() or "", "page": index})

    if _looks_like_scanned_pdf(pages):
        from app.rag.ocr import ocr_pdf_pages

        return ocr_pdf_pages(path)
    return pages


def _looks_like_scanned_pdf(pages: list[dict]) -> bool:
    if not pages:
        return False
    sample = pages[:SCAN_SAMPLE_PAGES]
    sample_chars = sum(len(page["text"].strip()) for page in sample)
    total_chars = sum(len(page["text"].strip()) for page in pages)
    return sample_chars == 0 or total_chars < MIN_EXTRACTED_CHARS


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _load_docx(path: Path) -> list[dict]:
    from docx import Document

    document = Document(str(path))
    image_map = _extract_docx_images(path)
    blocks: list[str] = []
    image_index = 1

    for child in document.element.body.iterchildren():
        tag = _local_name(child.tag)
        if tag == "p":
            text, image_index = _extract_xml_text(child, image_index, image_map)
            if text:
                blocks.append(text)
        elif tag == "tbl":
            for row in child.findall(".//w:tr", _NS):
                cells: list[str] = []
                for cell in row.findall("./w:tc", _NS):
                    cell_parts: list[str] = []
                    for paragraph in cell.findall("./w:p", _NS):
                        text, image_index = _extract_xml_text(paragraph, image_index, image_map)
                        if text:
                            cell_parts.append(text)
                    if cell_parts:
                        cells.append(" ".join(cell_parts))
                if cells:
                    blocks.append(" | ".join(cells))

    return [{"text": "\n".join(blocks), "page": None, "images": list(image_map.values())}]


def _extract_docx_images(path: Path) -> dict[str, str]:
    out_dir = Path("data/extracted_images") / path.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    rels: dict[str, str] = {}
    with ZipFile(path) as archive:
        rel_path = "word/_rels/document.xml.rels"
        if rel_path in archive.namelist():
            from xml.etree import ElementTree as ET

            root = ET.fromstring(archive.read(rel_path))
            for rel in root:
                rel_id = rel.attrib.get("Id")
                target = rel.attrib.get("Target", "")
                if rel_id and target.startswith("media/"):
                    rels[rel_id] = "word/" + target
        image_map: dict[str, str] = {}
        for rel_id, internal_path in rels.items():
            if internal_path not in archive.namelist():
                continue
            suffix = Path(internal_path).suffix or ".bin"
            output = out_dir / f"{rel_id}{suffix}"
            if not output.exists():
                output.write_bytes(archive.read(internal_path))
            image_map[rel_id] = str(output)
    return image_map


def _extract_xml_text(element, image_index: int, image_map: dict[str, str]) -> tuple[str, int]:
    parts: list[str] = []
    skipped_math_nodes: set[int] = set()

    for node in element.iter():
        local = _local_name(node.tag)
        if id(node) in skipped_math_nodes:
            continue
        if local in {"oMath", "oMathPara"}:
            math_text = _extract_math_text(node)
            if math_text:
                parts.append(f"[FORMULA:{math_text}]")
            for child in node.iter():
                skipped_math_nodes.add(id(child))
        elif local == "t" and node.text:
            parts.append(node.text)
        elif local == "tab":
            parts.append(" ")
        elif local in {"br", "cr"}:
            parts.append("\n")
        elif local == "blip":
            rel_id = node.attrib.get(f"{{{_NS['r']}}}embed") or node.attrib.get(f"{{{_NS['r']}}}link")
            image_path = image_map.get(rel_id or "", "")
            if image_path:
                parts.append(f"[IMAGE_{image_index}:{image_path}]")
            else:
                parts.append(f"[IMAGE_{image_index}]")
            image_index += 1
        elif local == "imagedata":
            rel_id = node.attrib.get(f"{{{_NS['r']}}}id")
            image_path = image_map.get(rel_id or "", "")
            if image_path:
                parts.append(f"[IMAGE_{image_index}:{image_path}]")
            else:
                parts.append(f"[IMAGE_{image_index}]")
            image_index += 1
        elif local == "object":
            # ???????? blip/imagedata???????????????
            continue

    text = "".join(parts)
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    return text.strip(), image_index


def _extract_math_text(element) -> str:
    tokens: list[str] = []
    for node in element.iter():
        if _local_name(node.tag) == "t" and node.text:
            tokens.append(node.text)
    return "".join(tokens).strip()
