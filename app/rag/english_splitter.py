from __future__ import annotations

import re
from dataclasses import dataclass

from app.rag.splitter import (
    AnswerBlock,
    MaterialBlock,
    Question,
    QuestionBlock,
    Section,
    _IMAGE_PATH_RX,
    _IMAGE_RX,
    _FORMULA_RX,
    _extract_options,
    _lookup_page,
    _remove_options,
    check_question_quality,
    detect_paper_layout,
    normalize_pages,
)


_QUESTION_RX = re.compile(r"(?m)^(?P<num>\d{1,3})\s*[.．、]\s*(?=\S)")
_GROUP_LABEL_RX = re.compile(r"^[A-E]\s*$")
_SECTION_RX = re.compile(
    r"^(?:第[一二三四五六七八]+部分|第[一二三四五六七八]+节|"
    r"(?:I|II|III|IV|V|VI|VII)\s*[.．]|Section\s+[A-C]|"
    r"参考答案|答案与解析|听力原文|听力材料|"
    r"完形填空|阅读理解|语法填空|七选五|应用文写作|读后续写|"
    r"Guided Writing|Translation|Summary Writing)",
    re.I,
)
_INLINE_ANSWER_RX = re.compile(r"【答案】(?P<body>.*?)(?=\n【(?:解析|导语|\d+题详解)】|$)", re.S)
_DETAIL_RX = re.compile(r"【(?P<num>\d{1,3})题详解】(?P<body>.*?)(?=\n【\d{1,3}题详解】|$)", re.S)
_RANGE_ANSWER_RX = re.compile(r"(?P<start>\d{1,3})\s*[-—~～至]\s*(?P<end>\d{1,3})\s*[:：]?\s*(?P<answers>[A-H]+)", re.I)
_NUMBERED_ANSWER_RX = re.compile(r"(?<!\d)(?P<num>\d{1,3})\s*[.．、:]\s*(?P<answer>[A-H](?:\s*[/、]\s*[A-H])?|[^\n]{1,80}?)(?=(?:\s+\d{1,3}\s*[.．、:])|$)", re.I)
_TRANSCRIPT_RX = re.compile(r"(?mi)^\(Text\s+(?P<text_no>\d{1,2})\)\s*(?P<body>.*?)(?=^\(Text\s+\d{1,2}\)|\Z)", re.S)
_LISTENING_RANGE_RX = re.compile(r"听第\s*(?P<text_no>\d{1,2})\s*段材料[^\n]*?第\s*(?P<start>\d{1,3})\s*(?:、|至|到|和|—|-)\s*(?P<end>\d{1,3})\s*题")
_IMAGE_TOKEN_RX = re.compile(r"\[IMAGE_\d+(?::[^\]]+)?\]")

_GROUP_TYPES = {"cloze", "grammar_fill", "vocabulary_fill", "gap_filling", "error_correction", "writing", "translation", "summary_writing"}
_CHOICE_TYPES = {"listening", "reading", "single_choice"}


@dataclass
class EnglishGroup:
    title: str
    text: str
    start: int
    page: int | None
    question_type: str


def _clean_line(line: str) -> str:
    return re.sub(r"[ \t\u3000]+", " ", line.replace("\xa0", " ")).strip()


def infer_english_question_type(title: str, text: str = "") -> str:
    value = f"{title} {text[:1200]}".lower()
    if "听力" in title:
        return "listening"
    if ("阅读" in title and ("第二节" in title or "section b" in title.lower())
            and ("填入空白处" in value or "多余选项" in value)):
        return "gap_filling"
    if "阅读" in title and re.search(r"(?:>\s*[A-E]$|第一节)", title, re.I):
        return "reading"
    if ("语言知识运用" in title or "语言运用" in title or "知识运用" in title):
        if "第一节" in title and ("最佳选项" in value or "掌握其大意" in value):
            return "cloze"
        if "第二节" in title and ("填入1个适当的单词" in value or "括号内" in value):
            return "grammar_fill"
    if "写作" in title:
        if "短文改错" in title:
            return "error_correction"
        return "writing"
    if "听力" in value or "listening" in value or "听下面" in value or "对话或独白" in value:
        return "listening"
    if "七选五" in value or ("选项中选出能填入空白处" in value or "选项中选出可以填入空白处" in value) or "one more than you need" in value:
        return "gap_filling"
    if ("完形填空" in value or "cloze" in value
            or ("阅读下面短文" in value and "填入空白处" in value and "最佳选项" in value)
            or "掌握其大意" in value):
        return "cloze"
    if ("语法填空" in value or "fill in the blanks to make the passage coherent" in value or "grammar" in value
            or "用括号内所给词" in value or "括号内单词" in value or "括号内所给单词" in value
            or "在未给提示词的空白处" in value or "填入1个适当的单词" in value):
        return "grammar_fill"
    if "fill in each blank" in value or "word chosen from the box" in value:
        return "vocabulary_fill"
    if "短文改错" in value or "共有10处语言错误" in value:
        return "error_correction"
    if "translation" in value or "翻译" in value:
        return "translation"
    if "summary writing" in value or "概要写作" in value:
        return "summary_writing"
    if ("guided writing" in value or "应用文写作" in value or "读后续写" in value
            or "write an english composition" in value or "书面表达" in value or "写作" in title):
        return "writing"
    if "阅读" in value or "reading" in value:
        return "reading"
    return "single_choice"


def _is_group_boundary(line: str, current_type: str, has_questions: bool) -> bool:
    if _SECTION_RX.match(line):
        return True
    if _GROUP_LABEL_RX.fullmatch(line) and has_questions and current_type in {"reading", "single_choice"}:
        return True
    return False


def split_english_groups(text: str, boundaries: list[tuple[int, int | None]]) -> list[EnglishGroup]:
    groups: list[EnglishGroup] = []
    title = ""
    parent_title = ""
    lines: list[str] = []
    start = 0
    offset = 0

    def flush() -> None:
        nonlocal lines
        body = "\n".join(lines).strip()
        if body:
            qtype = infer_english_question_type(title, body)
            groups.append(EnglishGroup(title, body, start, _lookup_page(start, boundaries), qtype))
        lines = []

    for raw_line in text.splitlines():
        line = _clean_line(raw_line)
        line_start = offset
        offset += len(raw_line) + 1
        if not line:
            continue
        qtype = infer_english_question_type(title, "\n".join(lines[:5]))
        if _is_group_boundary(line, qtype, bool(_QUESTION_RX.search("\n".join(lines)))):
            flush()
            if re.match(r"^第[一二三四五六七八]+部分", line):
                parent_title = line[:160]
                title = parent_title
            elif re.match(r"^(?:第[一二三四五六七八]+节|Section\s+[A-C])", line, re.I) and parent_title:
                title = f"{parent_title} > {line[:120]}"
            elif _GROUP_LABEL_RX.fullmatch(line) and title:
                title = f"{title.split(' > ')[0]} > {line}"
            else:
                title = line[:220]
                if line.startswith(("参考答案", "答案与解析", "听力原文", "听力材料")):
                    parent_title = ""
            start = line_start
            continue
        if not lines:
            start = line_start
        lines.append(line)
    flush()
    return groups


def _answer_map(text: str) -> dict[str, str]:
    answers: dict[str, str] = {}
    normalized = text.replace("\xa0", " ")
    for match in _RANGE_ANSWER_RX.finditer(normalized):
        start, end = int(match.group("start")), int(match.group("end"))
        values = re.sub(r"[^A-H]", "", match.group("answers").upper())
        if len(values) == end - start + 1:
            for number, value in zip(range(start, end + 1), values):
                answers[str(number)] = value
    for marker in _INLINE_ANSWER_RX.finditer(normalized):
        body = " ".join(marker.group("body").split())
        for item in re.finditer(r"(?<!\d)(\d{1,3})\s*[.．]\s*([A-H])(?=\s|$)", body, re.I):
            answers[item.group(1)] = item.group(2).upper()
        compact = re.findall(r"(?<!\d)(\d{1,3})\s*[-—~～至]\s*(\d{1,3})\s*[:：]?\s*([A-H]+)", body, re.I)
        for start_text, end_text, values in compact:
            start, end = int(start_text), int(end_text)
            if len(values) == end - start + 1:
                for number, value in zip(range(start, end + 1), values.upper()):
                    answers[str(number)] = value
    return answers


def _detail_map(text: str) -> dict[str, str]:
    return {match.group("num"): match.group("body").strip() for match in _DETAIL_RX.finditer(text)}


def _extract_inline_answer(text: str) -> str:
    match = _INLINE_ANSWER_RX.search(text)
    return " ".join(match.group("body").split()) if match else ""


def _strip_solution(text: str) -> str:
    positions = [pos for pos in (text.find("【答案】"), text.find("【解析】"), text.find("【导语】")) if pos >= 0]
    return text[: min(positions)].strip() if positions else text.strip()


def _images_and_formulas(text: str) -> tuple[list[str], list[str], list[str]]:
    images = _IMAGE_RX.findall(text)
    paths = [match.group(1).strip() for match in _IMAGE_PATH_RX.finditer(text)]
    formulas = _FORMULA_RX.findall(text)
    return images, paths, formulas


def _make_question(
    *, number: str, title: str, qtype: str, raw: str, material: str = "", material_id: str = "",
    answer: str = "", analysis: str = "", page: int | None = None, grouped: bool = False,
) -> Question:
    clean_raw = _strip_solution(raw)
    options = [] if grouped else _extract_options(clean_raw)
    stem = clean_raw if grouped else _remove_options(clean_raw)
    stem = re.sub(r"^\d{1,3}\s*[.．、]\s*", "", stem).strip()
    images, image_paths, formulas = _images_and_formulas("\n".join([material, raw]))
    if qtype == "listening":
        transcript_match = re.search(r"(?:【原文】|原文】)(?P<body>.*)$", raw, re.S)
        if transcript_match:
            material = transcript_match.group("body").strip()
            material_id = f"listening-inline-{number}"
    question = Question(
        question_no=number,
        section_title=title,
        question_type=qtype,
        stem=stem,
        options=options,
        answer=answer,
        analysis=analysis,
        images=images,
        image_paths=image_paths,
        formulas=formulas,
        raw_text=raw,
        page=page,
        material_id=material_id,
        material_excerpt=material.strip(),
        is_composition=qtype in {"writing", "translation", "summary_writing"},
        layout_type="english_grouped",
        subject="英语",
    )
    if answer or analysis:
        question.match_method = "inline_or_answer_table"
        question.match_confidence = 0.98 if answer else 0.9
    check_question_quality(question)
    if material_id and "has_material" not in question.quality_flags:
        question.quality_flags.append("has_material")
    if qtype in _GROUP_TYPES and not material.strip() and "missing_material" not in question.quality_flags:
        question.quality_flags.append("missing_material")
    return question


def _parse_individual_group(
    group: EnglishGroup, answer_map: dict[str, str], details: dict[str, str], material_counter: int,
) -> tuple[list[Question], list[MaterialBlock], int]:
    all_matches = list(_QUESTION_RX.finditer(group.text))
    matches = []
    last_number = -1
    for match in all_matches:
        number = int(match.group("num"))
        if matches and number <= last_number:
            continue
        matches.append(match)
        last_number = number
    if not matches:
        return [], [], material_counter
    count_match = re.search(r"共\s*(\d{1,3})\s*小题", group.title)
    if count_match:
        expected_count = int(count_match.group(1))
        first_number = int(matches[0].group("num"))
        maximum = first_number + expected_count - 1
        matches = [match for match in matches if int(match.group("num")) <= maximum][:expected_count]
    first = matches[0]
    material = group.text[: first.start()].strip()
    material_id = ""
    materials: list[MaterialBlock] = []
    if material and len(material) >= 40:
        material_counter += 1
        material_id = f"english-material-{material_counter}"
        materials.append(MaterialBlock(material_id, group.title, material, group.page))

    questions: list[Question] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(group.text)
        raw = group.text[start:end].strip()
        number = match.group("num")
        inline = _extract_inline_answer(raw)
        answer = answer_map.get(number, "")
        if not answer and inline:
            single = re.search(r"(?:^|\s)([A-H])(?:\s|$)", inline)
            answer = single.group(1) if single else inline[:80]
        analysis = details.get(number, "")
        if not analysis and "【解析】" in raw:
            analysis = raw.split("【解析】", 1)[1].strip()
        question = _make_question(
            number=number, title=group.title, qtype=group.question_type, raw=raw,
            material=material, material_id=material_id, answer=answer, analysis=analysis, page=group.page,
        )
        questions.append(question)
    return questions, materials, material_counter


def _declared_range(text: str, question_type: str = "") -> tuple[int, int] | None:
    patterns = (
        r"第\s*(\d{1,3})\s*(?:至|到|—|-)\s*(\d{1,3})\s*题",
        r"questions?\s+(\d{1,3})\s*(?:to|through|-)\s*(\d{1,3})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return int(match.group(1)), int(match.group(2))
    numbers = [int(match.group("num")) for match in _QUESTION_RX.finditer(text)]
    if not numbers:
        inline_numbers = [int(value) for value in re.findall(r"(?<!\d)(\d{1,3})\s*(?=\([^\n()]{1,30}\))", text)]
        numbers = inline_numbers
    if not numbers:
        return None
    if question_type in {"writing", "error_correction", "summary_writing"}:
        return numbers[0], numbers[0]
    unique = sorted(set(numbers))
    return unique[0], unique[-1]


def _parse_grouped_group(
    group: EnglishGroup, answer_map: dict[str, str], material_counter: int,
) -> tuple[list[Question], list[MaterialBlock], int]:
    body = group.text.strip()
    if len(body) < 20:
        return [], [], material_counter
    declared = _declared_range(f"{group.title}\n{body}", group.question_type)
    number = f"{declared[0]}-{declared[1]}" if declared else f"group-{material_counter + 1}"
    material_counter += 1
    material_id = f"english-material-{material_counter}"
    material_text = _strip_solution(body)
    materials = [MaterialBlock(material_id, group.title, material_text, group.page)]
    answers = []
    if declared and group.question_type in {"cloze", "grammar_fill", "vocabulary_fill", "gap_filling"}:
        answers = [f"{n}.{answer_map[str(n)]}" for n in range(declared[0], declared[1] + 1) if str(n) in answer_map]
    inline = _extract_inline_answer(body)
    answer = " ".join(answers) or inline
    analysis = body.split("【解析】", 1)[1].strip() if "【解析】" in body else ""
    question = _make_question(
        number=number, title=group.title, qtype=group.question_type, raw=body,
        material=material_text, material_id=material_id, answer=answer, analysis=analysis,
        page=group.page, grouped=True,
    )
    question.stem = material_text
    if declared and group.question_type in {"cloze", "grammar_fill", "vocabulary_fill", "gap_filling"} and len(answers) not in {0, declared[1] - declared[0] + 1}:
        question.quality_flags.append("answer_count_mismatch")
    return [question], materials, material_counter


def _attach_listening_transcripts(questions: list[Question], text: str) -> None:
    transcripts = {int(match.group("text_no")): match.group("body").strip() for match in _TRANSCRIPT_RX.finditer(text)}
    ranges = []
    for match in _LISTENING_RANGE_RX.finditer(text):
        ranges.append((int(match.group("start")), int(match.group("end")), int(match.group("text_no"))))
    for question in questions:
        if question.question_type != "listening" or not question.question_no.isdigit():
            continue
        number = int(question.question_no)
        text_no = next((item for start, end, item in ranges if start <= number <= end), number if number <= 5 else None)
        transcript = transcripts.get(text_no or -1, "")
        if question.material_id.startswith("listening-inline-"):
            continue
        if transcript:
            question.material_excerpt = transcript
            question.material_id = f"listening-text-{text_no}"
            if "has_material" not in question.quality_flags:
                question.quality_flags.append("has_material")
        elif "missing_transcript" not in question.quality_flags:
            question.quality_flags.append("missing_transcript")


class EnglishQuestionExtractor:
    def __init__(self, pages: list[dict]):
        self.pages = pages
        self.text = ""
        self.boundaries: list[tuple[int, int | None]] = []
        self.sections: list[Section] = []
        self.materials: list[MaterialBlock] = []
        self.answers: list[AnswerBlock] = []
        self.questions: list[Question] = []
        self.layout_type = "english_grouped"

    def extract(self) -> list[Question]:
        self.text, self.boundaries = normalize_pages(self.pages)
        groups = split_english_groups(self.text, self.boundaries)
        self.sections = [Section(group.title, group.text, group.start, group.page) for group in groups]
        answers = _answer_map(self.text)
        details = _detail_map(self.text)
        material_counter = 0
        for group in groups:
            if not group.title:
                continue
            if group.title.startswith(("参考答案", "答案与解析", "听力原文", "听力材料")):
                continue
            if group.question_type in _GROUP_TYPES:
                questions, materials, material_counter = _parse_grouped_group(group, answers, material_counter)
            else:
                questions, materials, material_counter = _parse_individual_group(group, answers, details, material_counter)
            self.questions.extend(questions)
            self.materials.extend(materials)
        _attach_listening_transcripts(self.questions, self.text)
        self.questions = _deduplicate_questions(self.questions)
        return self.questions


def _deduplicate_questions(questions: list[Question]) -> list[Question]:
    result: list[Question] = []
    seen: set[tuple[str, str, str]] = set()
    for question in questions:
        key = (question.question_type, question.question_no, re.sub(r"\s+", " ", question.stem)[:160])
        if key in seen:
            continue
        seen.add(key)
        result.append(question)
    return result
