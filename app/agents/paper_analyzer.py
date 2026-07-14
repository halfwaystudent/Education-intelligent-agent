from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from sqlalchemy.orm import Session

from app.agents.subject_agents import BaseSubjectAgent
from app.core.llm import get_chat_llm
from app.models.db import Chunk, Document
from app.rag.chains import citations_from_chunks
from app.rag.retriever import retrieve_chunks


SUPPORTED_PAPER_SUFFIXES = {".docx", ".pdf"}


def validate_paper_file_name(file_name: str) -> None:
    suffix = Path(file_name or "").suffix.lower()
    if suffix not in SUPPORTED_PAPER_SUFFIXES:
        allowed = "、".join(sorted(SUPPORTED_PAPER_SUFFIXES))
        raise ValueError(f"仅支持上传 {allowed} 试卷文件")


def analyze_indexed_paper(
    db: Session,
    document: Document,
    agent: BaseSubjectAgent,
    collection_name: str,
    question: str = "",
) -> dict:
    db_chunks = (
        db.query(Chunk)
        .filter(Chunk.document_id == document.id)
        .order_by(Chunk.id.asc())
        .all()
    )
    questions = [_question_from_chunk(chunk, document.file_name) for chunk in db_chunks]
    report = build_rule_report(
        document=document,
        subject=agent.subject,
        agent_name=agent.name,
        report_focus=agent.report_focus,
        questions=questions,
        user_question=question,
    )
    report = maybe_refine_report(report, agent, questions, question)

    retrieve_query = question.strip() or _default_retrieve_query(agent.subject, document.file_name, questions)
    retrieved_chunks = retrieve_chunks(retrieve_query, course_id=document.course_id, collection_name=collection_name)
    citations = citations_from_chunks(retrieved_chunks)

    return {
        "report_markdown": report,
        "questions": questions,
        "citations": citations,
        "retrieved_chunks": retrieved_chunks,
    }


def _question_from_chunk(chunk: Chunk, file_name: str) -> dict:
    meta = chunk.metadata_json or {}
    stem = _clean_text(meta.get("stem") or chunk.content)
    analysis = _clean_text(meta.get("analysis", ""))
    answer = _clean_text(meta.get("answer", ""))
    options = meta.get("options") or []
    if isinstance(options, str):
        options = [item.strip() for item in options.split(";") if item.strip()]
    quality_flags = meta.get("quality_flags") or []
    if isinstance(quality_flags, str):
        quality_flags = [item.strip() for item in quality_flags.split(";") if item.strip()]

    return {
        "question_no": str(meta.get("question_no", "")),
        "question_type": str(meta.get("question_type", "") or "未知题型"),
        "stem": stem,
        "options": options,
        "answer": answer,
        "analysis": analysis,
        "knowledge_points": infer_knowledge_points(stem, analysis),
        "page": chunk.page,
        "source_file": file_name,
        "question_image_path": str(meta.get("question_image_path", "")),
        "question_image_url": str(meta.get("question_image_url", "")),
        "display_html": str(meta.get("display_html", "")),
        "display_image_paths": _metadata_list(meta.get("display_image_paths")),
        "display_image_urls": _metadata_list(meta.get("display_image_urls")),
        "quality_flags": quality_flags,
        "chunk_id": chunk.chunk_id,
    }


def _metadata_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value or "").split(";") if item.strip()]


def infer_knowledge_points(stem: str, analysis: str) -> list[str]:
    text = f"{stem}\n{analysis}"
    candidates = [
        "函数", "导数", "数列", "向量", "概率", "几何", "立体几何", "解析几何", "三角函数",
        "阅读理解", "文言文", "古诗文", "语言文字运用", "作文", "论述类文本", "现代文阅读",
        "完形填空", "语法", "词汇", "翻译", "写作", "阅读", "主旨大意", "细节理解",
    ]
    hits = [item for item in candidates if item in text]
    if hits:
        return hits[:6]
    words = re.findall(r"[\u4e00-\u9fff]{2,8}|[A-Za-z]{4,}", text)
    stop_words = {"答案", "解析", "分析", "详解", "因为", "所以", "根据", "下列", "已知", "选择"}
    ranked = [word for word, _ in Counter(words).most_common(6) if word not in stop_words]
    return ranked[:4]


def build_rule_report(
    document: Document,
    subject: str,
    agent_name: str,
    report_focus: str,
    questions: list[dict],
    user_question: str = "",
) -> str:
    total = len(questions)
    type_counts = Counter(q.get("question_type") or "未知题型" for q in questions)
    missing = sum(1 for q in questions if q.get("quality_flags"))
    knowledge = Counter(point for q in questions for point in q.get("knowledge_points", []))
    representative = _representative_questions(questions)

    lines = [
        f"# {subject}试卷解析报告",
        "",
        "## 试卷基本信息",
        f"- 文件名：{document.file_name}",
        f"- 使用 Agent：{agent_name}",
        f"- 解析题目数：{total}",
        f"- 分析侧重点：{report_focus}",
    ]
    if user_question.strip():
        lines.append(f"- 用户分析要求：{user_question.strip()}")
    if missing:
        lines.append(f"- 识别提示：有 {missing} 个题目存在答案、解析、选项或题干字段不完整，建议展示时保留原文引用核对。")

    lines.extend(["", "## 题型统计"])
    if type_counts:
        lines.extend(f"- {name}：{count} 题" for name, count in type_counts.items())
    else:
        lines.append("- 暂未识别出明确题型。")

    lines.extend(["", "## 主要知识点"])
    if knowledge:
        lines.extend(f"- {name}：关联 {count} 题" for name, count in knowledge.most_common(8))
    else:
        lines.append("- 当前文本中未提取到稳定知识点，可结合题目原文进一步标注。")

    lines.extend(["", "## 代表题解析"])
    if representative:
        for item in representative:
            no = item.get("question_no") or "-"
            qtype = item.get("question_type") or "未知题型"
            stem = _truncate(item.get("stem", ""), 180)
            answer = item.get("answer") or "未识别"
            analysis = _truncate(item.get("analysis", ""), 220) or "原解析未完整识别，建议结合试卷原文查看。"
            points = "、".join(item.get("knowledge_points", [])[:4]) or "待补充"
            lines.extend([
                f"### 第 {no} 题（{qtype}）",
                f"- 题干摘要：{stem}",
                f"- 参考答案：{answer}",
                f"- 解析摘要：{analysis}",
                f"- 关联知识点：{points}",
            ])
    else:
        lines.append("- 暂无可展示的代表题。")

    lines.extend([
        "",
        "## 易错点提醒",
        _mistake_advice(subject),
        "",
        "## 后续复习建议",
        _review_advice(subject, knowledge),
        "",
        "## 引用来源",
        f"- 本报告基于上传文件 `{document.file_name}` 的解析结果生成。",
        "- 前端可继续展示每道题的 `chunk_id`、页码和原始题目图片路径，便于追溯。",
    ])
    return "\n".join(lines)


def maybe_refine_report(report: str, agent: BaseSubjectAgent, questions: list[dict], user_question: str = "") -> str:
    llm = get_chat_llm()
    if llm is None:
        return report
    samples = "\n".join(
        f"第{q.get('question_no') or '-'}题 {q.get('question_type')}: {_truncate(q.get('stem', ''), 120)}"
        for q in questions[:8]
    )
    prompt = f"""你是{agent.subject}试卷分析智能体 {agent.name}。请在不编造题目信息的前提下，润色下面的 Markdown 试卷报告。

学科侧重点：{agent.report_focus}
用户额外要求：{user_question or '无'}
题目样例：
{samples}

原报告：
{report}

请保留 Markdown 结构，输出更适合教师演示的报告。"""
    try:
        content = llm.invoke(prompt).content
        return content or report
    except Exception:
        return report


def _representative_questions(questions: list[dict]) -> list[dict]:
    picked: list[dict] = []
    seen_types: set[str] = set()
    for item in questions:
        qtype = item.get("question_type") or "未知题型"
        if qtype not in seen_types:
            picked.append(item)
            seen_types.add(qtype)
        if len(picked) >= 5:
            break
    return picked or questions[:5]


def _mistake_advice(subject: str) -> str:
    if subject == "数学":
        return "- 注意审题条件、公式适用范围、计算符号和证明步骤完整性，避免只写结论。"
    if subject == "英语":
        return "- 注意定位原文依据、区分同义替换和干扰项，写作题要兼顾语法准确性与表达连贯性。"
    return "- 注意结合文本依据作答，文言文和诗歌题要落实关键词解释，作文题要先明确立意与材料关系。"


def _review_advice(subject: str, knowledge: Counter) -> str:
    top = "、".join(name for name, _ in knowledge.most_common(5))
    if not top:
        top = "本卷高频题型"
    if subject == "数学":
        return f"- 优先复习 {top}，每类题至少整理一道典型题的条件转化和标准步骤。"
    if subject == "英语":
        return f"- 优先复习 {top}，把错题按词汇、句法、篇章逻辑和写作表达分类整理。"
    return f"- 优先复习 {top}，把阅读题答案依据、语言运用规则和作文素材分开整理。"


def _default_retrieve_query(subject: str, file_name: str, questions: list[dict]) -> str:
    points = [point for q in questions[:8] for point in q.get("knowledge_points", [])]
    return f"{subject} {file_name} " + " ".join(points[:8])


def _clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _truncate(value: str, limit: int) -> str:
    value = _clean_text(value)
    return value if len(value) <= limit else value[:limit].rstrip() + "..."
