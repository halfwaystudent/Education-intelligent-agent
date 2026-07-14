from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import get_settings
from app.rag.render_question import enrich_chunks_with_visual_ocr


@dataclass
class Section:
    title: str
    text: str
    start: int = 0
    page: int | None = None


@dataclass
class MaterialBlock:
    material_id: str
    section_title: str
    text: str
    page: int | None = None


@dataclass
class AnswerBlock:
    question_no: str
    section_title: str = ""
    answer: str = ""
    analysis: str = ""
    score_rule: str = ""
    match_method: str = ""
    match_confidence: float = 0.0
    matched: bool = False
    raw_text: str = ""


@dataclass
class QuestionBlock:
    question_no: str
    section_title: str
    question_type: str
    raw_text: str
    page: int | None = None


@dataclass
class Question:
    question_no: str
    section_title: str
    question_type: str
    stem: str = ""
    options: list[str] = field(default_factory=list)
    answer: str = ""
    analysis: str = ""
    comment: str = ""
    images: list[str] = field(default_factory=list)
    formulas: list[str] = field(default_factory=list)
    image_paths: list[str] = field(default_factory=list)
    display_html: str = ""
    raw_text: str = ""
    page: int | None = None
    quality_flags: list[str] = field(default_factory=list)
    material_id: str = ""
    material_excerpt: str = ""
    score_rule: str = ""
    match_method: str = ""
    match_confidence: float = 0.0
    unmatched_reason: str = ""
    is_composition: bool = False
    layout_type: str = ""
    question_no_inferred: bool = False
    subject: str = ""


CN_NUM = "一二三四五六七八九十"
QUESTION_TYPES = "选择题|填空题|解答题|阅读理解|现代文阅读|文言文阅读|古代诗歌阅读|语言文字运用|微写作|作文|写作"
_NOISE_LINE_PATTERNS = [
    re.compile(r"^\s*第?\s*\d+\s*页\s*/\s*共?\s*\d+\s*页?\s*$"),
    re.compile(r"^.*(?:www\.|kzx\.com|x\.com).*$", re.I),
    re.compile(r"^.*(?:高考在线|京考一点通|获取更多试题资料|排名分析信息).*$"),
]
_MULTI_SPACE_RX = re.compile(r"[ \t\u3000]{2,}")
_SECTION_RX = re.compile(
    rf"^(?:[{CN_NUM}]+[、.．]\s*(?:{QUESTION_TYPES}).*|(?:{QUESTION_TYPES}).*|"
    r"(?:参考答案|答案与解析|参考答案与试题解析|试题解析|答案解析|评分标准).*)$"
)
_CHINESE_SECTION_RX = re.compile(
    r"^(?:[一二三四五六七八九十]+[、.．]\s*.+|"
    r"（[一二三四五六七八九十]+）\s*.+|"
    r"(?:现代文|实用类文本|文学类文本|文言文|古代诗歌|古诗文|语言文字|名篇名句|阅读|微写作|写作|作文).*)$"
)
_QUESTION_LINE_RX = re.compile(r"^(?P<num>\d{1,2})\s*[.．、](?!\d)\s*(?:【[^】]{1,12}】|\[[^\]]{1,12}\]|\S).*$")
_SUB_QUESTION_RX = re.compile(r"^[（(](?P<num>\d{1,2})[）)]\s*\S.*$")
_INLINE_QUESTION_RX = re.compile(r"(?<!\d)(?P<num>\d{1,2})\s*[.．、](?!\d)\s*(?=【|\[|[\u4e00-\u9fffA-Za-z（(])")
_OPTION_START_RX = re.compile(r"(?m)(?:^|\s)([A-H])[.．、]\s*")
_ANSWER_ENTRY_RX = re.compile(
    r"(?<!\d)(?P<num>\d{1,2})\s*[.．、](?!\d)\s*(?P<body>.*?)"
    r"(?=(?<!\d)\d{1,2}\s*[.．、]\s*|$)",
    re.S,
)
_DETAIL_MARK_RX = re.compile(r"^【\s*(?P<num>\d{1,2})\s*题(?:详解|解析)\s*】\s*(?P<body>.*)$")
_TAIL_ANSWER_HEADING_RX = re.compile(r"^(?:参考答案|答案与解析|参考答案与试题解析|试题答案|参考答案及评分意见)\s*$")
_SCORE_RX = re.compile(r"^(?:评分说明|评分标准|评分意见)\s*[：:]?\s*(.*)$")
_ANSWER_MARKERS = ["【答案】", "[答案]", "答案：", "答案:", "故选：", "故答案为："]
_ANALYSIS_MARKERS = ["【解析】", "[解析]", "【分析】", "【详解】", "【解答】", "解析：", "分析：", "详解："]
_COMMENT_MARKERS = ["【点睛】", "【点评】", "点评：", "点睛："]
_IMAGE_RX = re.compile(r"\[IMAGE_\d+(?::[^\]]+)?\]")
_IMAGE_PATH_RX = re.compile(r"\[IMAGE_\d+:([^\]]+)\]")
_FORMULA_RX = re.compile(r"\[FORMULA:[^\]]+\]")
_CHINESE_FEATURES = ("语文", "现代文阅读", "文言文", "古代诗歌", "语言文字运用", "名篇名句", "作文", "写作")


def normalize_pages(pages: list[dict]) -> tuple[str, list[tuple[int, int | None]]]:
    parts: list[str] = []
    boundaries: list[tuple[int, int | None]] = []
    offset = 0
    for page in pages:
        lines: list[str] = []
        for raw_line in (page.get("text", "") or "").replace("\r\n", "\n").replace("\r", "\n").splitlines():
            line = _MULTI_SPACE_RX.sub(" ", raw_line).strip()
            if not line or any(pattern.match(line) for pattern in _NOISE_LINE_PATTERNS):
                continue
            lines.append(line)
        if not lines:
            continue
        page_text = "\n".join(lines)
        boundaries.append((offset, page.get("page")))
        parts.append(page_text)
        offset += len(page_text) + 1
    return "\n".join(parts).strip(), boundaries


def _lookup_page(offset: int, boundaries: list[tuple[int, int | None]]) -> int | None:
    page = None
    for start, page_no in boundaries:
        if start <= offset:
            page = page_no
        else:
            break
    return page


def split_sections(text: str, boundaries: list[tuple[int, int | None]] | None = None) -> list[Section]:
    sections: list[Section] = []
    current_title = ""
    current_lines: list[str] = []
    current_start = 0
    offset = 0

    def flush() -> None:
        nonlocal current_lines
        body = "\n".join(current_lines).strip()
        if body:
            page = _lookup_page(current_start, boundaries or []) if boundaries else None
            sections.append(Section(current_title, body, current_start, page))
        current_lines = []

    for line in text.splitlines():
        line_start = offset
        offset += len(line) + 1
        if _SECTION_RX.match(line):
            flush()
            current_title = line[:220]
            current_start = line_start
            continue
        if not current_lines:
            current_start = line_start
        current_lines.append(line)
    flush()
    if not sections and text.strip():
        sections.append(Section("", text.strip(), 0, None))
    return sections


def infer_question_type(section_title: str) -> str:
    if "选择题" in section_title:
        return "选择题"
    if "填空题" in section_title or "名篇名句" in section_title:
        return "填空题"
    if "解答题" in section_title:
        return "解答题"
    if "微写作" in section_title:
        return "微写作题"
    if "作文" in section_title or "写作" in section_title:
        return "作文题"
    if "文言文" in section_title:
        return "文言文阅读"
    if "诗歌" in section_title or "古诗" in section_title:
        return "古代诗歌阅读"
    if "语言文字" in section_title:
        return "语言文字运用"
    if "阅读" in section_title or "文本" in section_title:
        return "阅读题"
    return "试题"


def _is_question_section(section: Section) -> bool:
    return bool(section.title and not re.search(r"答案|解析|评分", section.title))


def split_question_blocks(sections: list[Section]) -> list[QuestionBlock]:
    blocks: list[QuestionBlock] = []
    for section in sections:
        if not _is_question_section(section):
            continue
        matches = list(_find_question_starts(section.text))
        for index, match in enumerate(matches):
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(section.text)
            raw_text = section.text[start:end].strip()
            if len(raw_text) >= 20:
                blocks.append(QuestionBlock(match.group("num"), section.title, infer_question_type(section.title), raw_text, section.page))
    return blocks


def _find_question_starts(text: str):
    line_matches: list[_OffsetMatch] = []
    offset = 0
    for line in text.splitlines():
        match = _QUESTION_LINE_RX.match(line)
        if match:
            line_matches.append(_OffsetMatch(match, offset))
        offset += len(line) + 1
    if len(line_matches) >= 2:
        return line_matches
    return list(_INLINE_QUESTION_RX.finditer(text))


class _OffsetMatch:
    def __init__(self, match: re.Match, offset: int):
        self._match = match
        self._offset = offset

    def start(self) -> int:
        return self._offset

    def group(self, name: str):
        return self._match.group(name)


def parse_question(block: QuestionBlock) -> Question:
    text = block.raw_text.strip()
    images = _IMAGE_RX.findall(text)
    image_paths = [match.group(1).strip() for match in _IMAGE_PATH_RX.finditer(text)]
    formulas = _FORMULA_RX.findall(text)
    comment = _extract_after_markers(text, _COMMENT_MARKERS)
    text_without_comment = _strip_after_markers(text, _COMMENT_MARKERS)
    analysis = _extract_after_markers(text_without_comment, _ANALYSIS_MARKERS)
    text_without_analysis = _strip_after_markers(text_without_comment, _ANALYSIS_MARKERS)
    answer = _extract_answer(text_without_analysis)
    stem_area = _strip_after_markers(text_without_analysis, _ANSWER_MARKERS)
    options = _extract_options(stem_area)
    stem = _remove_options(stem_area).strip()
    return Question(
        question_no=block.question_no,
        section_title=block.section_title,
        question_type=block.question_type,
        stem=stem,
        options=options,
        answer=answer,
        analysis=analysis,
        comment=comment,
        images=images,
        formulas=formulas,
        image_paths=image_paths,
        display_html=_to_display_html(block.raw_text),
        raw_text=block.raw_text,
        page=block.page,
    )


def _find_first_marker(text: str, markers: list[str]) -> tuple[int, str] | None:
    found = None
    for marker in markers:
        index = text.find(marker)
        if index >= 0 and (found is None or index < found[0]):
            found = (index, marker)
    return found


def _extract_after_markers(text: str, markers: list[str]) -> str:
    found = _find_first_marker(text, markers)
    if not found:
        return ""
    index, marker = found
    return text[index + len(marker) :].strip()


def _strip_after_markers(text: str, markers: list[str]) -> str:
    found = _find_first_marker(text, markers)
    return text if not found else text[: found[0]].strip()


def _extract_answer(text: str) -> str:
    answer = _extract_after_markers(text, _ANSWER_MARKERS)
    if not answer:
        return ""
    stop = _find_first_marker(answer, _ANALYSIS_MARKERS + _COMMENT_MARKERS)
    if stop:
        answer = answer[: stop[0]]
    return answer.strip().splitlines()[0].strip() if answer.strip() else ""


def _extract_options(text: str) -> list[str]:
    starts = list(_OPTION_START_RX.finditer(text))
    options: list[str] = []
    for index, match in enumerate(starts):
        label = match.group(1)
        start = match.end()
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        value = text[start:end].strip()
        if "【" in value:
            value = value.split("【", 1)[0].strip()
        option = f"{label}. {value}" if value else f"{label}."
        if option not in options:
            options.append(option)
    return options


def _remove_options(text: str) -> str:
    starts = list(_OPTION_START_RX.finditer(text))
    return text if not starts else text[: starts[0].start()].strip()


def is_chinese_paper(text: str) -> bool:
    score = sum(1 for feature in _CHINESE_FEATURES if feature in text)
    return "语文" in text[:500] or score >= 3


def detect_paper_layout(text: str) -> str:
    tail_positions = [match.start() for match in re.finditer(r"(?m)^(?:参考答案|答案与解析|试题答案|参考答案及评分意见)\s*[:：]?\s*$", text)]
    inline_count = text.count("【答案】") + text.count("【解析】") + text.count("【详解】")
    if tail_positions and inline_count:
        return "hybrid"
    if tail_positions:
        return "tail_answer"
    return "inline_analysis"


def _split_tail_answer_text(text: str) -> tuple[str, str]:
    match = re.search(r"(?m)^(?:参考答案|答案与解析|试题答案|参考答案及评分意见)\s*[:：]?\s*$", text)
    if not match:
        return text, ""
    return text[: match.start()].strip(), text[match.end() :].strip()


def _strip_inline_solution_blocks(text: str) -> str:
    lines = text.splitlines()
    kept: list[str] = []
    in_solution = False
    solution_max_no = 0
    for line in lines:
        if "【答案】" in line:
            prefix = line.split("【答案】", 1)[0].strip()
            if prefix:
                kept.append(prefix)
            previous_numbers = [
                int(match.group("num"))
                for previous_line in kept
                if (match := _QUESTION_LINE_RX.match(previous_line))
            ]
            solution_max_no = previous_numbers[-1] if previous_numbers else 0
            in_solution = True
            continue
        if in_solution:
            if _is_chinese_section_heading(line) and not line.startswith(("【", "答案", "解析", "详解")):
                in_solution = False
                kept.append(line)
                continue
            question_match = _QUESTION_LINE_RX.match(line)
            if (
                question_match
                and int(question_match.group("num")) == solution_max_no + 1
                and _looks_like_numbered_question(line)
            ):
                in_solution = False
                kept.append(line)
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def _is_chinese_section_heading(line: str) -> bool:
    if line.startswith(("写作时", "写作中", "作文可以", "作文时", "写作思路", "写作指导", "作文指导")):
        return False
    return bool(_CHINESE_SECTION_RX.match(line)) and not bool(_QUESTION_LINE_RX.match(line))


def _question_line_match(line: str) -> re.Match | None:
    return _QUESTION_LINE_RX.match(line)


def _material_excerpt(text: str, limit: int = 2400) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned if len(cleaned) <= limit else cleaned[:limit].rstrip() + "…"


def _declared_question_range(title: str) -> tuple[int, int] | None:
    match = re.search(r"完成第?\s*(\d{1,2})\s*[—–-]\s*(\d{1,2})\s*题", title or "")
    if not match:
        return None
    start, end = int(match.group(1)), int(match.group(2))
    return (start, end) if start <= end else None


def _looks_like_unnumbered_question(line: str) -> bool:
    if not re.search(r"[（(]\s*\d+\s*分\s*[）)]\s*$", line):
        return False
    return bool(
        re.match(
            r"^(?:请|赏析|分析|概括|解释|简述|结合|根据|把|翻译|指出|第[①-⑳一二三四五六七八九十\d]|下列|文中|画线|达了)",
            line,
        )
    ) and "1点1分" not in line


def _looks_like_numbered_question(line: str) -> bool:
    match = _QUESTION_LINE_RX.match(line)
    if not match:
        return False
    body = line[match.end("num") :].lstrip(".．、 ")
    if len(body) < 6 or re.fullmatch(r"[A-H](?:\s+.*)?", body):
        return False
    return bool(
        re.match(
            r"^(?:请|赏析|分析|概括|解释|简述|结合|根据|把|翻译|指出|补写|在横线|下列|文中|阅读|学校|从下面|微写作)",
            body,
        )
        or re.search(r"[（(]\s*\d+\s*分\s*[）)]", body)
        or (len(body) >= 20 and bool(re.search(r"[\u4e00-\u9fff]", body)))
    )


def _parse_chinese_question_area(text: str, boundaries: list[tuple[int, int | None]] | None = None) -> tuple[list[MaterialBlock], list[Question]]:
    materials: list[MaterialBlock] = []
    questions: list[Question] = []
    section_title = ""
    context_lines: list[str] = []
    current_lines: list[str] = []
    current_no = ""
    current_page: int | None = None
    group_material: MaterialBlock | None = None
    material_counter = 0
    offset = 0
    declared_range: tuple[int, int] | None = None
    inferred_current = False

    def finalize_question() -> None:
        nonlocal current_lines, current_no, inferred_current
        if not current_no or not current_lines:
            current_lines = []
            current_no = ""
            return
        raw_text = "\n".join(current_lines).strip()
        block = QuestionBlock(current_no, section_title, infer_question_type(section_title), raw_text, current_page)
        question = parse_question(block)
        question.question_no_inferred = inferred_current
        if group_material:
            question.material_id = group_material.material_id
            question.material_excerpt = _material_excerpt(group_material.text)
        question.is_composition = question.question_type in {"作文题", "微写作题"} or "不少于800字" in raw_text
        questions.append(question)
        current_lines = []
        current_no = ""
        inferred_current = False

    for line in text.splitlines():
        line_start = offset
        offset += len(line) + 1
        if _is_chinese_section_heading(line):
            finalize_question()
            section_title = line[:220]
            declared_range = _declared_question_range(section_title)
            context_lines = [line]
            group_material = None
            continue

        match = _question_line_match(line) if section_title else None
        if match:
            if current_no:
                finalize_question()
            elif group_material is None:
                material_text = "\n".join(context_lines).strip()
                if len(material_text) >= 20:
                    material_counter += 1
                    group_material = MaterialBlock(
                        material_id=f"material-{material_counter}",
                        section_title=section_title,
                        text=material_text,
                        page=_lookup_page(line_start, boundaries or []),
                    )
                    materials.append(group_material)
            current_no = match.group("num")
            inferred_current = False
            current_page = _lookup_page(line_start, boundaries or [])
            current_lines = [line]
            continue

        if not current_no and declared_range and _looks_like_unnumbered_question(line):
            if group_material is None:
                material_text = "\n".join(context_lines).strip()
                if len(material_text) >= 20:
                    material_counter += 1
                    group_material = MaterialBlock(
                        material_id=f"material-{material_counter}",
                        section_title=section_title,
                        text=material_text,
                        page=_lookup_page(line_start, boundaries or []),
                    )
                    materials.append(group_material)
            current_no = str(declared_range[0])
            inferred_current = True
            current_page = _lookup_page(line_start, boundaries or [])
            current_lines = [f"{current_no}. {line}"]
            continue

        if current_no and declared_range and _looks_like_unnumbered_question(line):
            next_no = int(current_no) + 1
            if declared_range[0] <= next_no <= declared_range[1]:
                finalize_question()
                current_no = str(next_no)
                inferred_current = True
                current_page = _lookup_page(line_start, boundaries or [])
                current_lines = [f"{next_no}. {line}"]
                continue

        if current_no:
            current_lines.append(line)
        else:
            context_lines.append(line)

    finalize_question()
    return materials, questions


def _parse_answer_entries(text: str, section_title: str = "") -> list[AnswerBlock]:
    entries: list[AnswerBlock] = []
    normalized = re.sub(r"(?<=\S)[ \t]+(?=\d{1,2}\s*[.．、])", "\n", text.strip())
    matches = list(_ANSWER_ENTRY_RX.finditer(normalized))
    for match in matches:
        body = match.group("body").strip()
        if not body:
            continue
        entries.append(
            AnswerBlock(
                question_no=match.group("num"),
                section_title=section_title,
                answer=body,
                raw_text=match.group(0).strip(),
            )
        )
    return entries


def _extract_inline_answer_blocks(text: str) -> list[AnswerBlock]:
    blocks: list[AnswerBlock] = []
    answer_markers = list(re.finditer(r"【答案】", text))
    for marker_index, marker in enumerate(answer_markers):
        next_answer = answer_markers[marker_index + 1].start() if marker_index + 1 < len(answer_markers) else len(text)
        analysis_marker = re.search(r"【(?:解析|详解)】", text[marker.end() : next_answer])
        answer_end = marker.end() + analysis_marker.start() if analysis_marker else next_answer
        answer_text = text[marker.end() : answer_end].strip()
        parsed = _parse_answer_entries(_IMAGE_RX.sub("[图片]", answer_text))
        if not parsed:
            previous_questions = [
                match
                for line in text[: marker.start()].splitlines()
                if (match := _QUESTION_LINE_RX.match(line))
            ]
            if previous_questions and answer_text:
                parsed = [AnswerBlock(previous_questions[-1].group("num"), answer=answer_text, raw_text=answer_text)]
        blocks.extend(parsed)

        analysis_start = marker.end() + analysis_marker.end() if analysis_marker else answer_end
        analysis_text = text[analysis_start:next_answer]
        details = list(re.finditer(r"【\s*(\d{1,2})\s*题(?:详解|解析)\s*】", analysis_text))
        for detail_index, detail in enumerate(details):
            detail_end = details[detail_index + 1].start() if detail_index + 1 < len(details) else len(analysis_text)
            detail_body = analysis_text[detail.end() : detail_end].strip()
            target = next((item for item in reversed(blocks) if item.question_no == detail.group(1)), None)
            if target:
                target.analysis = detail_body
            else:
                blocks.append(AnswerBlock(detail.group(1), analysis=detail_body, raw_text=detail.group(0) + detail_body))
        if analysis_marker and not details and parsed:
            parsed[-1].analysis = analysis_text.strip()
    return blocks


def _extract_tail_answer_blocks(text: str) -> list[AnswerBlock]:
    blocks: list[AnswerBlock] = []
    current_section = ""
    current: AnswerBlock | None = None

    def flush() -> None:
        nonlocal current
        if current:
            current.answer = current.answer.strip()
            current.analysis = current.analysis.strip()
            current.score_rule = current.score_rule.strip()
            current.raw_text = current.raw_text.strip()
            blocks.append(current)
        current = None

    for line in text.splitlines():
        if _is_chinese_section_heading(line) or re.match(r"^（[一二三四五六七八九十]+）", line):
            flush()
            current_section = line[:220]
            continue
        match = _QUESTION_LINE_RX.match(line)
        if match:
            flush()
            body = line[match.end("num") :].lstrip(".．、 ")
            current = AnswerBlock(match.group("num"), current_section, answer=body, raw_text=line)
            continue
        score_match = _SCORE_RX.match(line)
        if score_match and current:
            value = score_match.group(1).strip()
            current.score_rule = "\n".join(part for part in [current.score_rule, value] if part)
            current.raw_text += "\n" + line
            continue
        if current:
            if line in {"【解析】", "【详解】"}:
                continue
            if line.startswith(("审题：", "立意：", "【解析】", "【详解】")) or current.analysis:
                current.analysis = "\n".join(part for part in [current.analysis, line] if part)
            else:
                current.answer = "\n".join(part for part in [current.answer, line] if part)
            current.raw_text += "\n" + line
    flush()
    return blocks


def extract_chinese_materials_and_questions(sections: list[Section]) -> tuple[list[MaterialBlock], list[Question]]:
    text = "\n".join("\n".join(part for part in [section.title, section.text] if part) for section in sections)
    question_text, _ = _split_tail_answer_text(text)
    question_text = _strip_inline_solution_blocks(question_text)
    return _parse_chinese_question_area(question_text)


def extract_chinese_answer_blocks(sections: list[Section], layout: str) -> list[AnswerBlock]:
    text = "\n".join("\n".join(part for part in [section.title, section.text] if part) for section in sections)
    _, tail_text = _split_tail_answer_text(text)
    answers = _extract_inline_answer_blocks(text if layout != "tail_answer" else "")
    if tail_text:
        answers.extend(_extract_tail_answer_blocks(tail_text))
    return answers


def merge_chinese_answers(questions: list[Question], answers: list[AnswerBlock]) -> list[Question]:
    by_number: dict[str, list[Question]] = {}
    for question in questions:
        by_number.setdefault(question.question_no, []).append(question)

    for answer in answers:
        candidates = by_number.get(answer.question_no, [])
        unmatched = [question for question in candidates if not question.answer and not question.analysis]
        target = unmatched[0] if len(unmatched) == 1 else None
        method = "question_no"
        confidence = 0.98

        if target is None and answer.section_title:
            section_candidates = [
                question
                for question in candidates
                if _section_key(question.section_title) == _section_key(answer.section_title)
                and not question.answer
                and not question.analysis
            ]
            if len(section_candidates) == 1:
                target = section_candidates[0]
                method = "section_question_no"
                confidence = 0.92

        if target is None and len(candidates) == 1:
            target = candidates[0]
            method = "question_no_merge"
            confidence = 0.88

        if target is None:
            continue

        if answer.answer:
            target.answer = answer.answer
        if answer.analysis:
            target.analysis = answer.analysis
        if answer.score_rule:
            target.score_rule = answer.score_rule
        target.match_method = method
        target.match_confidence = confidence
        answer.match_method = method
        answer.match_confidence = confidence
        answer.matched = True

    return questions


def _section_key(title: str) -> str:
    return re.sub(r"[\s（）()一二三四五六七八九十、.．\d分题]", "", title or "")[:30]


def build_unmatched_answer_chunks(answers: list[AnswerBlock], layout_type: str = "") -> list[dict]:
    chunks: list[dict] = []
    for answer in answers:
        if answer.matched:
            continue
        content = "\n".join(part for part in [answer.answer, answer.analysis, answer.score_rule] if part).strip()
        if not content:
            continue
        compact = re.sub(r"\s+", "", content)
        if re.fullmatch(r"[A-H]", compact, re.I) or len(compact) < 8:
            continue
        if "将答案写在答题卡" in content or "本卷共" in content:
            continue
        flags = ["unmatched_answer"]
        chunks.append(
            {
                "content": content,
                "display_html": "".join(
                    [
                        _html_section("答案", answer.answer, "answer"),
                        _html_section("解析", answer.analysis, "analysis"),
                        _html_section("评分说明", answer.score_rule, "score-rule"),
                    ]
                ),
                "embedding_text": "\n".join(
                    part
                    for part in [
                        "学科：语文",
                        f"栏目：{answer.section_title}" if answer.section_title else "",
                        f"题号：{answer.question_no}",
                        f"答案：{_clean_for_embedding(answer.answer)}" if answer.answer else "",
                        f"解析：{_clean_for_embedding(answer.analysis)}" if answer.analysis else "",
                        f"评分说明：{_clean_for_embedding(answer.score_rule)}" if answer.score_rule else "",
                    ]
                    if part
                ),
                "page": None,
                "section_title": answer.section_title,
                "question_no": answer.question_no,
                "question_type": "答案解析",
                "chunk_type": "unmatched_answer",
                "quality_flags": flags,
                "stem": "",
                "options": [],
                "answer": answer.answer,
                "analysis": answer.analysis,
                "comment": "",
                "score_rule": answer.score_rule,
                "images": [],
                "image_paths": [],
                "formulas": [],
                "raw_text": answer.raw_text,
                "material_id": "",
                "match_method": "",
                "match_confidence": 0.0,
                "has_material": False,
                "is_composition": False,
                "layout_type": layout_type,
            }
        )
    return chunks


class ChineseQuestionExtractor:
    def __init__(self, pages: list[dict]):
        self.pages = pages
        self.text = ""
        self.boundaries: list[tuple[int, int | None]] = []
        self.sections: list[Section] = []
        self.materials: list[MaterialBlock] = []
        self.answers: list[AnswerBlock] = []
        self.questions: list[Question] = []
        self.layout_type = ""

    def extract(self) -> list[Question]:
        self.text, self.boundaries = normalize_pages(self.pages)
        self.sections = split_sections(self.text, self.boundaries)
        self.layout_type = detect_paper_layout(self.text)
        question_text, tail_text = _split_tail_answer_text(self.text)
        self.materials, self.questions = _parse_chinese_question_area(
            _strip_inline_solution_blocks(question_text), self.boundaries
        )
        self.answers = _extract_inline_answer_blocks(question_text)
        if tail_text:
            self.answers.extend(_extract_tail_answer_blocks(tail_text))
        self.questions = merge_chinese_answers(self.questions, self.answers)
        for question in self.questions:
            question.layout_type = self.layout_type
            check_question_quality(question)
        return self.questions


def check_question_quality(question: Question) -> Question:
    flags: list[str] = []
    if len(question.stem.strip()) < 8:
        flags.append("missing_stem")
    if question.question_type == "选择题" and len(question.options) < 4:
        flags.append("missing_options")
    if not question.answer and not question.is_composition:
        flags.append("missing_answer")
    if not question.analysis and not question.is_composition:
        flags.append("missing_analysis")
    if question.material_id:
        flags.append("has_material")
    if question.images:
        flags.append("has_image")
        if any(path.lower().endswith((".wmf]", ".emf]")) for path in question.images):
            flags.append("has_formula_image")
    if question.formulas:
        flags.append("has_formula")
    if question.match_method and question.match_confidence < 0.9:
        flags.append("low_match_confidence")
    if question.question_no_inferred:
        flags.append("inferred_question_no")
    question.quality_flags = flags
    return question


def _prepare_display_asset(image_path: str) -> tuple[str, str]:
    try:
        from app.rag.image_ocr import display_image_url, prepare_image_for_display

        rendered = prepare_image_for_display(image_path)
        return str(rendered), display_image_url(rendered)
    except Exception:
        return "", ""


def _to_display_html(text: str) -> str:
    parts: list[str] = []
    cursor = 0
    for match in _IMAGE_RX.finditer(text or ""):
        parts.append(html.escape(text[cursor : match.start()]).replace("\n", "<br>\n"))
        token = match.group(0)
        path_match = _IMAGE_PATH_RX.match(token)
        if path_match:
            source_path = path_match.group(1).strip()
            _, image_url = _prepare_display_asset(source_path)
            label = html.escape(Path(source_path).name)
            if image_url:
                parts.append(f'<img class="formula-img" src="{html.escape(image_url)}" alt="{label}" loading="lazy">')
            else:
                parts.append(f'<span class="formula-missing" title="{label}">[公式]</span>')
        else:
            parts.append('<span class="formula-missing">[公式]</span>')
        cursor = match.end()
    parts.append(html.escape(text[cursor:]).replace("\n", "<br>\n"))
    return "".join(parts)


def _clean_for_embedding(text: str) -> str:
    from app.storage.vectorstore import sanitize_embedding_text

    return sanitize_embedding_text(text, max_chars=0)


def _clip_embedding_field(text: str, limit: int) -> str:
    value = _clean_for_embedding(text)
    if limit > 0 and len(value) > limit:
        return value[:limit].rstrip() + "…"
    return value


def _html_section(title: str, text: str, css_class: str) -> str:
    if not text:
        return ""
    return f'<section class="{css_class}"><h4>{html.escape(title)}</h4>{_to_display_html(text)}</section>'


def build_chunk(question: Question) -> dict:
    content_parts = [question.material_excerpt, question.stem]
    if question.options:
        content_parts.append("\n".join(question.options))
    if question.answer:
        content_parts.append(f"答案：{question.answer}")
    if question.analysis:
        content_parts.append(f"解析：{question.analysis}")
    if question.score_rule:
        content_parts.append(f"评分说明：{question.score_rule}")
    if question.comment:
        content_parts.append(f"点评：{question.comment}")
    raw_content = "\n".join(part for part in content_parts if part).strip() or question.raw_text
    content = _clean_for_embedding(raw_content)

    display_html = "".join(
        [
            _html_section("材料", question.material_excerpt, "material"),
            _html_section("题干", question.stem, "stem"),
            (
                '<section class="options"><h4>选项</h4>'
                + "".join(f'<div class="option">{_to_display_html(option)}</div>' for option in question.options)
                + "</section>"
                if question.options
                else ""
            ),
            _html_section("答案", question.answer, "answer"),
            _html_section("解析", question.analysis, "analysis"),
            _html_section("评分说明", question.score_rule, "score-rule"),
            _html_section("点评", question.comment, "comment"),
        ]
    )

    display_assets = [_prepare_display_asset(path) for path in question.image_paths]
    display_image_paths = [path for path, _ in display_assets if path]
    display_image_urls = [url for _, url in display_assets if url]

    # Keep discriminative fields before long explanations so token truncation
    # does not discard the question or its source material.
    embedding_parts = [
        f"学科：{question.subject}" if question.subject else ("学科：语文" if question.layout_type else ""),
        f"栏目：{_clip_embedding_field(question.section_title, 180)}",
        f"题型：{question.question_type}",
        f"题号：{question.question_no}",
        f"题干：{_clip_embedding_field(question.stem, 800)}",
    ]
    if question.material_excerpt:
        embedding_parts.append(f"材料摘要：{_clip_embedding_field(question.material_excerpt, 900)}")
    if question.answer:
        embedding_parts.append(f"答案：{_clip_embedding_field(question.answer, 400)}")
    if question.options:
        options_text = "；".join(_clip_embedding_field(option, 180) for option in question.options)
        embedding_parts.append(f"选项：{_clip_embedding_field(options_text, 700)}")
    if question.analysis:
        embedding_parts.append(f"解析：{_clip_embedding_field(question.analysis, 1200)}")
    if question.score_rule:
        embedding_parts.append(f"评分说明：{_clip_embedding_field(question.score_rule, 300)}")

    return {
        "content": content,
        "display_html": display_html,
        "embedding_text": "\n".join(part for part in embedding_parts if part),
        "page": question.page,
        "section_title": question.section_title,
        "question_no": question.question_no,
        "question_type": question.question_type,
        "chunk_type": "composition" if question.is_composition else ("analysis" if question.analysis else "question"),
        "quality_flags": question.quality_flags,
        "stem": question.stem,
        "options": question.options,
        "answer": question.answer,
        "analysis": question.analysis,
        "comment": question.comment,
        "score_rule": question.score_rule,
        "images": question.images,
        "image_paths": question.image_paths,
        "display_image_paths": display_image_paths,
        "display_image_urls": display_image_urls,
        "formulas": question.formulas,
        "raw_text": question.raw_text,
        "material_excerpt": question.material_excerpt,
        "material_id": question.material_id,
        "match_method": question.match_method,
        "match_confidence": question.match_confidence,
        "has_material": bool(question.material_id),
        "is_composition": question.is_composition,
        "layout_type": question.layout_type,
        "subject": question.subject,
        "unmatched_reason": question.unmatched_reason,
    }


class QuestionExtractor:
    def __init__(self, pages: list[dict], subject: str = ""):
        self.pages = pages
        self.subject = subject.strip()
        self.text = ""
        self.boundaries: list[tuple[int, int | None]] = []
        self.sections: list[Section] = []
        self.blocks: list[QuestionBlock] = []
        self.questions: list[Question] = []
        self.materials: list[MaterialBlock] = []
        self.answers: list[AnswerBlock] = []
        self.layout_type = ""
        self.is_chinese = False
        self.is_english = False
        self.is_math = False

    def extract(self) -> list[Question]:
        self.text, self.boundaries = normalize_pages(self.pages)
        self.is_english = self.subject == "英语"
        if self.is_english:
            from app.rag.english_splitter import EnglishQuestionExtractor

            english = EnglishQuestionExtractor(self.pages)
            self.questions = english.extract()
            self.text = english.text
            self.boundaries = english.boundaries
            self.sections = english.sections
            self.materials = english.materials
            self.answers = english.answers
            self.layout_type = english.layout_type
            return self.questions
        self.is_math = self.subject == "\u6570\u5b66"
        if self.is_math:
            from app.rag.math_splitter import MathQuestionExtractor

            math = MathQuestionExtractor(self.pages)
            self.questions = math.extract()
            self.text = math.text
            self.boundaries = math.boundaries
            self.sections = math.sections
            self.blocks = math.blocks
            self.materials = math.materials
            self.answers = math.answers
            self.layout_type = math.layout_type
            if self.questions:
                return self.questions
        self.is_chinese = is_chinese_paper(self.text)
        if self.is_chinese:
            chinese = ChineseQuestionExtractor(self.pages)
            self.questions = chinese.extract()
            self.text = chinese.text
            self.boundaries = chinese.boundaries
            self.sections = chinese.sections
            self.materials = chinese.materials
            self.answers = chinese.answers
            self.layout_type = chinese.layout_type
            if len(self.questions) >= 3:
                return self.questions

        self.sections = split_sections(self.text, self.boundaries)
        self.blocks = split_question_blocks(self.sections)
        self.questions = [check_question_quality(parse_question(block)) for block in self.blocks]
        return self.questions


def _fallback_split(full_text: str) -> list[dict]:
    settings = get_settings()
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        separators=["\n\n", "\n", "。", "？", "！", "；", ". ", " ", ""],
    )
    return [
        {
            "content": _clean_for_embedding(piece.strip()),
            "embedding_text": _clip_embedding_field(piece.strip(), 1800),
            "page": None,
            "section_title": "",
            "question_no": "",
            "question_type": "文本",
            "chunk_type": "question",
            "quality_flags": ["fallback_split"],
        }
        for piece in splitter.split_text(full_text)
        if piece.strip()
    ]


def split_documents(pages: list[dict], subject: str = "") -> list[dict]:
    extractor = QuestionExtractor(pages, subject=subject)
    questions = extractor.extract()
    if questions:
        if extractor.is_math:
            from app.rag.image_ocr import prepare_images_for_display

            prepare_images_for_display(
                [image_path for question in questions for image_path in question.image_paths]
            )
        chunks = [build_chunk(question) for question in questions]
        if extractor.is_chinese:
            chunks.extend(build_unmatched_answer_chunks(extractor.answers, extractor.layout_type))
        return enrich_chunks_with_visual_ocr(chunks)
    return _fallback_split(extractor.text)


def guess_section_title(text: str, fallback: str = "") -> str:
    for line in text.splitlines():
        if _is_chinese_section_heading(line) or _SECTION_RX.match(line):
            return line[:220]
    return fallback
