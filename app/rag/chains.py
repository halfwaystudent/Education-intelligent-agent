import re
from collections.abc import Iterator
from typing import Any

from app.core.llm import get_chat_llm
from app.rag.prompts import COURSE_QA_PROMPT, PROBLEM_SOLVING_PROMPT
from app.rag.retriever import retrieve_chunks

PROBLEM_KEYWORDS = ("求解", "计算", "证明", "题", "已知", "答案", "步骤", "推导")
CONCEPT_KEYWORDS = ("是什么", "概念", "解释", "定义", "区别", "联系", "为什么")
OUT_OF_SCOPE_KEYWORDS = ("天气", "股票", "娱乐", "闲聊", "笑话")
IMAGE_TOKEN_RX = re.compile(r"\[IMAGE_\d+(?::[^\]]*)?(?:\]|$)")
FORMULA_TOKEN_RX = re.compile(r"\[FORMULA:[^\]]+\]")
BARE_IMAGE_PATH_RX = re.compile(r"\b\d+\.(?:jpeg|jpg|png|gif|webp)\]\[IMAGE_\d+:[^\]]*(?:\]|$)", re.I)


def route_question(question: str) -> str:
    text = question.strip()
    if any(keyword in text for keyword in OUT_OF_SCOPE_KEYWORDS):
        return "out_of_scope"
    if any(keyword in text for keyword in PROBLEM_KEYWORDS):
        return "problem_solving"
    if any(keyword in text for keyword in CONCEPT_KEYWORDS):
        return "concept_explain"
    return "knowledge_qa"


def build_context(chunks: list[dict]) -> str:
    blocks = []
    for index, item in enumerate(chunks, start=1):
        meta = item["metadata"]
        source = f"{meta.get('file_name', '')} p.{meta.get('page') or '-'} {meta.get('section_title') or ''}".strip()
        blocks.append(f"[资料{index}] {source}\n{clean_chunk_text(item['content'])}")
    return "\n\n".join(blocks)


def clean_chunk_text(text: str) -> str:
    value = str(text or "")
    value = BARE_IMAGE_PATH_RX.sub("[图片/公式]", value)
    value = IMAGE_TOKEN_RX.sub("[图片/公式]", value)
    value = FORMULA_TOKEN_RX.sub(lambda match: match.group(0).removeprefix("[FORMULA:").removesuffix("]"), value)
    value = re.sub(r"(?i)rld\d*|rid\d*", "", value)
    value = re.sub(r"(题型：\S+\s+题号：\S+)\s+\1", r"\1", value)
    value = re.sub(r"(?:(题型：[^\s]{1,12})\s*){2,}", r"\1 ", value)
    value = re.sub(r"(?:(题号：\S+)\s*){2,}", r"\1 ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def citations_from_chunks(chunks: list[dict]) -> list[dict]:
    seen = set()
    citations = []
    for item in chunks:
        meta = item["metadata"]
        chunk_id = str(meta.get("chunk_id", ""))
        if not chunk_id or chunk_id in seen:
            continue
        seen.add(chunk_id)
        page = meta.get("page")
        citations.append({
            "file_name": str(meta.get("file_name", "")),
            "page": int(page) if str(page).isdigit() else None,
            "section_title": str(meta.get("section_title", "")),
            "chunk_id": chunk_id,
        })
    return citations


def estimate_confidence(chunks: list[dict]) -> str:
    if not chunks:
        return "low"
    best = max(item.get("score", 0.0) for item in chunks)
    if best >= 0.55 and len(chunks) >= 2:
        return "high"
    if best >= 0.25:
        return "medium"
    return "low"


def fallback_answer(question: str, route: str, chunks: list[dict]) -> str:
    if not chunks:
        return "资料中没有明确说明。当前课程知识库还没有检索到足够相关的内容，建议先导入课程讲义、教材片段或教师资料后再提问。"
    context_points = []
    for index, item in enumerate(chunks[:3], start=1):
        text = clean_chunk_text(item["content"])
        context_points.append(f"{index}. {text[:240]}")
    if route == "problem_solving":
        return "已检索到可能相关的课程资料，但当前未配置聊天模型，先给出可追溯的解析骨架：\n\n涉及知识点：见引用资料。\n解题思路：围绕题干条件与引用资料中的定义、公式或步骤建立对应关系。\n分步过程：\n" + "\n".join(context_points) + "\n最终答案：需要配置 LLM 后生成完整推导。\n常见错误提醒：不要脱离引用资料直接套用未导入的知识。"
    return "已检索到以下课程资料。当前未配置聊天模型，因此只返回基于原文的保守摘要：\n" + "\n".join(context_points)


def prepare_question(question: str, course_id: int | None = None, collection_name: str | None = None) -> dict[str, Any]:
    route = route_question(question)
    if route == "out_of_scope":
        return {"question": question, "route": route, "chunks": [], "citations": [], "confidence": "low"}
    chunks = retrieve_chunks(question, course_id=course_id, collection_name=collection_name)
    return {
        "question": question,
        "route": route,
        "chunks": chunks,
        "citations": citations_from_chunks(chunks),
        "confidence": estimate_confidence(chunks),
    }


def _prompt_for(prepared: dict[str, Any]) -> str:
    prompt_template = PROBLEM_SOLVING_PROMPT if prepared["route"] == "problem_solving" else COURSE_QA_PROMPT
    return prompt_template.format(question=prepared["question"], context=build_context(prepared["chunks"]))


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("text"):
                parts.append(str(item["text"]))
        return "".join(parts)
    return str(value or "")


def stream_prepared_answer(prepared: dict[str, Any]) -> Iterator[str]:
    route = prepared["route"]
    chunks = prepared["chunks"]
    if route == "out_of_scope":
        yield "这个问题不属于当前课程知识库答疑范围。请提供课程概念、讲义内容或题目文本，我会基于资料回答。"
        return
    llm = get_chat_llm()
    if llm is None or not chunks:
        yield fallback_answer(prepared["question"], route, chunks)
        return
    for chunk in llm.stream(_prompt_for(prepared)):
        text = _content_text(getattr(chunk, "content", ""))
        if text:
            yield text


def answer_prepared_question(prepared: dict[str, Any]) -> str:
    return "".join(stream_prepared_answer(prepared))


def answer_question(question: str, course_id: int | None = None, collection_name: str | None = None) -> dict:
    prepared = prepare_question(question, course_id=course_id, collection_name=collection_name)
    answer = answer_prepared_question(prepared)
    return {
        "answer": answer,
        "citations": prepared["citations"],
        "route": prepared["route"],
        "confidence": prepared["confidence"],
        "retrieved_chunks": prepared["chunks"],
    }
