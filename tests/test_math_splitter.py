from app.rag.math_splitter import MathQuestionExtractor
from app.rag.splitter import QuestionExtractor, build_chunk


def _pages(text: str) -> list[dict]:
    return [{"text": text, "page": 1}]


def test_full_math_paper_keeps_stem_options_answer_and_analysis() -> None:
    text = """注意事项：
1.答题前填写姓名。
一、选择题：本题共2小题
1. 已知集合A，求A的补集（ ）
A. 甲 B. 乙 C. 丙 D. 丁
【答案】C
【解析】根据补集定义可得。
2. 已知函数f(x)，求其最小值（ ）
A. 0 B. 1 C. 2 D. 3
【答案】A
【解析】使用配方法可得。
"""
    questions = MathQuestionExtractor(_pages(text)).extract()

    assert [question.question_no for question in questions] == ["1", "2"]
    assert questions[0].stem.startswith("已知集合")
    assert len(questions[0].options) == 4
    assert questions[0].answer == "C"
    assert questions[0].analysis == "根据补集定义可得。"
    assert questions[0].subject == "数学"
    assert questions[0].layout_type == "math_full_question"


def test_answer_only_math_paper_becomes_question_level_chunks() -> None:
    text = """注意事项：
1.答卷前填写姓名。
2.选择题每小题选出答案后填涂。
3.非选择题必须写在答题卡上。
1．C
【分析】根据复数运算法则求解。
【详解】计算可得虚部为1。
2．BD
【分析】逐项判断。
【详解】B、D满足条件。
3．(1)证明见解析；(2)2
【分析】先证明垂直，再计算长度。
【详解】证明过程略。
"""
    extractor = MathQuestionExtractor(_pages(text))
    questions = extractor.extract()

    assert [question.question_no for question in questions] == ["1", "2", "3"]
    assert [question.question_type for question in questions] == ["选择题", "多项选择题", "解答题"]
    assert questions[0].answer == "C"
    assert questions[0].stem == ""
    assert "复数运算法则" in questions[0].analysis
    assert "answer_only_source" in questions[0].quality_flags
    assert extractor.layout_type == "math_answer_only"


def test_question_extractor_routes_math_and_builds_math_embedding_text() -> None:
    text = """一、填空题：本题共1小题
1. 函数[FORMULA:f(x)=x^2]的最小值为____。
【答案】0
【解析】因为[FORMULA:f(x)=x^2]恒大于等于0。
"""
    extractor = QuestionExtractor(_pages(text), subject="数学")
    question = extractor.extract()[0]
    chunk = build_chunk(question)

    assert chunk["subject"] == "数学"
    assert chunk["question_type"] == "填空题"
    assert "学科：数学" in chunk["embedding_text"]
    assert "f(x)=x^2" in chunk["embedding_text"]

def test_missing_image_only_question_does_not_drop_later_questions() -> None:
    text = """一、选择题
1. 第一题（ ）
A. 甲 B. 乙 C. 丙 D. 丁
【答案】A
【解析】第一题解析。
3. 第三题（ ）
A. 甲 B. 乙 C. 丙 D. 丁
【答案】B
【解析】第三题解析。
4. 第四题（ ）
A. 甲 B. 乙 C. 丙 D. 丁
【答案】C
【解析】第四题解析。
"""
    questions = MathQuestionExtractor(_pages(text)).extract()

    assert [question.question_no for question in questions] == ["1", "3", "4"]

def test_math_chunk_uses_browser_image_urls(monkeypatch) -> None:
    import app.rag.splitter as splitter_module

    monkeypatch.setattr(
        splitter_module,
        "_prepare_display_asset",
        lambda path: (f"data/image_ocr_rendered/mock/{path.split('/')[-1]}.png", "/media/formulas/mock/formula.png"),
    )
    text = """一、填空题
1. 已知[IMAGE_1:mock/formula.wmf]，求其值。
【答案】1
【解析】直接计算。
"""
    question = MathQuestionExtractor(_pages(text)).extract()[0]
    chunk = build_chunk(question)

    assert '<img class="formula-img"' in chunk["display_html"]
    assert 'src="/media/formulas/mock/formula.png"' in chunk["display_html"]
    assert "formula-link" not in chunk["display_html"]
    assert chunk["display_image_urls"] == ["/media/formulas/mock/formula.png"]
