from __future__ import annotations

import re
from dataclasses import dataclass

from app.rag.splitter import (
    Question,
    QuestionBlock,
    Section,
    _ANALYSIS_MARKERS,
    _COMMENT_MARKERS,
    _FORMULA_RX,
    _IMAGE_PATH_RX,
    _IMAGE_RX,
    _extract_after_markers,
    _extract_answer,
    _extract_options,
    _lookup_page,
    _strip_after_markers,
    check_question_quality,
    normalize_pages,
    parse_question,
)


_MATH_QUESTION_RX = re.compile(r"^\s*(?P<num>\d{1,2})\s*(?P<sep>[.．、])\s*(?P<body>\S.*)$")
_MATH_SECTION_RX = re.compile(
    r"^(?:[一二三四五六七八九十]+[、.．]\s*)?"
    r"(?:单项选择题|多项选择题|选择题|填空题|解答题|计算题|证明题|应用题).*$"
)
_SOLUTION_MARK_RX = re.compile(r"【(?:答案|解析|分析|详解|解答|小问\d+详解|点睛|点评)】")
_EXPLICIT_ANSWER_RX = re.compile(r"(?:\u3010\u7b54\u6848\u3011|\[\u7b54\u6848\]|(?:^|\n)\u7b54\u6848\s*[\uff1a:])")

_PREAMBLE_PREFIXES = (
    "答题前",
    "答卷前",
    "选择题的作答",
    "选择题每小题",
    "填空题和解答题的作答",
    "非选择题必须",
    "考试结束后",
)


@dataclass
class _MathStart:
    number: int
    offset: int


def infer_math_question_type(section_title: str, raw_text: str = "", answer_only: bool = False) -> str:
    title = section_title or ""
    if "多项选择" in title:
        return "多项选择题"
    if "选择题" in title:
        return "选择题"
    if "填空题" in title:
        return "填空题"
    if any(token in title for token in ("解答题", "计算题", "证明题", "应用题")):
        return "解答题"

    first_line = raw_text.splitlines()[0] if raw_text.splitlines() else ""
    first_match = _MATH_QUESTION_RX.match(first_line)
    first_body = first_match.group("body").strip() if first_match else ""
    if answer_only:
        compact = re.sub(r"\s+", "", first_body).rstrip(".．")
        if re.fullmatch(r"[A-H]{2,}", compact, re.I):
            return "多项选择题"
        if re.fullmatch(r"[A-H]", compact, re.I):
            return "选择题"
        if re.match(r"^[（(]\s*1\s*[）)]", first_body) or "证明见解析" in first_body:
            return "解答题"
        return "填空题"

    if len(_extract_options(raw_text)) >= 2:
        return "选择题"
    if re.search(r"[（(]\s*1\s*[）)]", raw_text[:800]):
        return "解答题"
    return "试题"


def _math_sections(text: str, boundaries: list[tuple[int, int | None]]) -> list[Section]:
    sections: list[Section] = []
    offset = 0
    for line in text.splitlines():
        cleaned = line.strip()
        if _MATH_SECTION_RX.match(cleaned):
            sections.append(Section(cleaned[:220], "", offset, _lookup_page(offset, boundaries)))
        offset += len(line) + 1
    return sections


def _question_candidates(text: str) -> list[_MathStart]:
    candidates: list[_MathStart] = []
    offset = 0
    for line in text.splitlines():
        match = _MATH_QUESTION_RX.match(line)
        if match:
            body = match.group("body").strip()
            if not body.startswith(_PREAMBLE_PREFIXES):
                candidates.append(_MathStart(int(match.group("num")), offset))
        offset += len(line) + 1
    return candidates


def _best_sequential_starts(candidates: list[_MathStart]) -> list[_MathStart]:
    if not candidates:
        return []

    # Some DOCX files lose an image-only question during extraction. Use the
    # longest increasing question-number sequence so a missing number does not
    # discard every later question.
    lengths = [1] * len(candidates)
    previous: list[int | None] = [None] * len(candidates)
    for index, candidate in enumerate(candidates):
        for prior in range(index):
            if candidates[prior].number >= candidate.number:
                continue
            score = lengths[prior] + 1
            if score > lengths[index]:
                lengths[index] = score
                previous[index] = prior

    valid_ends = [index for index, item in enumerate(candidates) if item.number >= 2]
    end_index = max(valid_ends or range(len(candidates)), key=lambda index: (lengths[index], candidates[index].number))
    result: list[_MathStart] = []
    cursor: int | None = end_index
    while cursor is not None:
        result.append(candidates[cursor])
        cursor = previous[cursor]
    result.reverse()
    return result


def _section_for_offset(sections: list[Section], offset: int) -> str:
    title = ""
    for section in sections:
        if section.start <= offset:
            title = section.title
        else:
            break
    return title


def _looks_answer_only(raw_text: str) -> bool:
    if _EXPLICIT_ANSWER_RX.search(raw_text):
        return False
    marker = _SOLUTION_MARK_RX.search(raw_text)
    if not marker:
        return False
    prefix = raw_text[: marker.start()].strip()
    lines = [line.strip() for line in prefix.splitlines() if line.strip()]
    if len(lines) != 1:
        return False
    match = _MATH_QUESTION_RX.match(lines[0])
    return bool(match and len(match.group("body").strip()) <= 240)


def _strip_number(text: str) -> str:
    return re.sub(r"^\s*\d{1,2}\s*[.．、]\s*", "", text, count=1).strip()


def _parse_math_question(
    raw_text: str, number: str, title: str, page: int | None, force_answer_only: bool = False
) -> Question:
    answer_only = force_answer_only or _looks_answer_only(raw_text)
    qtype = infer_math_question_type(title, raw_text, answer_only)
    block = QuestionBlock(number, title or ("答案解析" if answer_only else "数学试题"), qtype, raw_text, page)

    if not answer_only:
        question = parse_question(block)
        question.stem = _strip_number(question.stem)
    else:
        answer = _strip_number(raw_text.splitlines()[0])
        comment = _extract_after_markers(raw_text, _COMMENT_MARKERS)
        without_comment = _strip_after_markers(raw_text, _COMMENT_MARKERS)
        analysis = _extract_after_markers(without_comment, _ANALYSIS_MARKERS)
        if not answer:
            answer = _extract_answer(without_comment)
        question = Question(
            question_no=number,
            section_title=block.section_title,
            question_type=qtype,
            stem="",
            answer=answer,
            analysis=analysis,
            comment=comment,
            images=_IMAGE_RX.findall(raw_text),
            image_paths=[match.group(1).strip() for match in _IMAGE_PATH_RX.finditer(raw_text)],
            formulas=_FORMULA_RX.findall(raw_text),
            raw_text=raw_text,
            page=page,
            unmatched_reason="source_contains_answer_and_analysis_only",
        )

    question.subject = "数学"
    question.layout_type = "math_answer_only" if answer_only else "math_full_question"
    check_question_quality(question)
    if answer_only and "answer_only_source" not in question.quality_flags:
        question.quality_flags.append("answer_only_source")
    return question


class MathQuestionExtractor:
    def __init__(self, pages: list[dict]):
        self.pages = pages
        self.text = ""
        self.boundaries: list[tuple[int, int | None]] = []
        self.sections: list[Section] = []
        self.blocks: list[QuestionBlock] = []
        self.questions: list[Question] = []
        self.materials = []
        self.answers = []
        self.layout_type = "math"

    def extract(self) -> list[Question]:
        self.text, self.boundaries = normalize_pages(self.pages)
        self.sections = _math_sections(self.text, self.boundaries)
        starts = _best_sequential_starts(_question_candidates(self.text))
        force_answer_only = bool(starts and not self.sections and not _EXPLICIT_ANSWER_RX.search(self.text) and _SOLUTION_MARK_RX.search(self.text))
        for index, start in enumerate(starts):
            end = starts[index + 1].offset if index + 1 < len(starts) else len(self.text)
            raw_text = self.text[start.offset:end].strip()
            title = _section_for_offset(self.sections, start.offset)
            page = _lookup_page(start.offset, self.boundaries)
            question = _parse_math_question(raw_text, str(start.number), title, page, force_answer_only)
            self.questions.append(question)
            self.blocks.append(
                QuestionBlock(question.question_no, question.section_title, question.question_type, raw_text, page)
            )
        if self.questions and all(question.layout_type == "math_answer_only" for question in self.questions):
            self.layout_type = "math_answer_only"
        else:
            self.layout_type = "math_full_question"
        return self.questions
