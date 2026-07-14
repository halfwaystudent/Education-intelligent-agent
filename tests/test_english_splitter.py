from __future__ import annotations

from app.rag.splitter import QuestionExtractor, build_chunk


def _pages(text: str) -> list[dict]:
    return [{"text": text, "page": 1}]


def test_inline_answers_do_not_hide_later_listening_questions() -> None:
    text = """第一部分 听力（共两节，满分30分）
第一节（共2小题；每小题1.5分）
听下面2段对话，从A、B、C三个选项中选出最佳选项。
1. What is the man doing?
A. Reading. B. Running. C. Cooking.
【答案】A
【解析】He has a book.
2. Where are they?
A. At school. B. At home. C. At work.
【答案】B
【解析】They mention the kitchen.
"""
    extractor = QuestionExtractor(_pages(text), subject="英语")
    questions = extractor.extract()
    assert [question.question_no for question in questions] == ["1", "2"]
    assert [question.answer for question in questions] == ["A", "B"]
    assert all(question.question_type == "listening" for question in questions)


def test_cloze_is_kept_as_one_group() -> None:
    text = """第三部分 语言运用（共两节，满分30分）
第一节（共3小题；每小题1分）
阅读下面短文，从每题所给的A、B、C、D四个选项中选出最佳选项。
A student ____21____ home and ____22____ a book before she ____23____ asleep.
21. A. went B. goes C. go D. going
22. A. reads B. read C. reading D. reader
23. A. falls B. fell C. falling D. fall
【答案】21. A 22. B 23. B
【解析】考查上下文和时态。
"""
    questions = QuestionExtractor(_pages(text), subject="英语").extract()
    assert len(questions) == 1
    assert questions[0].question_type == "cloze"
    assert questions[0].question_no == "21-23"
    assert questions[0].answer.split() == ["21.A", "22.B", "23.B"]


def test_english_chunk_has_subject_and_material() -> None:
    text = """第二部分 阅读（共两节，满分50分）
第一节（共1小题；每小题2.5分）
A
This is a short passage with enough context for retrieval.
21. What is the passage about?
A. Art. B. Travel. C. Food. D. Sport.
【答案】B
【解析】The passage discusses a journey.
"""
    question = QuestionExtractor(_pages(text), subject="英语").extract()[0]
    chunk = build_chunk(question)
    assert chunk["subject"] == "英语"
    assert chunk["embedding_text"].startswith("学科：英语")
    assert chunk["material_id"]
    assert "This is a short passage" in chunk["display_html"]
