from collections import Counter
import re

from app.core.config import get_settings
from app.storage.vectorstore import get_chroma_collection

_EXCLUDED_QUALITY_FLAGS = {"fallback_split", "unmatched_answer"}


def _quality_flags(metadata: dict) -> set[str]:
    value = metadata.get("quality_flags") or ""
    if isinstance(value, list):
        return {str(item).strip() for item in value if str(item).strip()}
    return {item.strip() for item in str(value).split(";") if item.strip()}


def _query_boost(question: str, content: str, metadata: dict) -> float:
    query = question.lower()
    qtype = str(metadata.get("question_type") or "").lower()
    boost = 0.0
    type_rules = [
        (("seven-option", "seven option", "coherence", "七选五"), {"gap_filling"}),
        (("grammar", "verb tense", "语法填空"), {"grammar_fill"}),
        (("cloze", "完形填空"), {"cloze"}),
        (("listening", "听力"), {"listening"}),
        (("write a letter", "email", "giving advice", "建议信"), {"writing"}),
    ]
    for keywords, expected_types in type_rules:
        if any(keyword in query for keyword in keywords) and qtype in expected_types:
            boost += 0.08
            break

    if any(keyword in query for keyword in ("meaning of a word", "meaning from context", "猜测词义")):
        if re.search(r"what does .{0,80}(?:mean|refer to)|underlined .{0,60}(?:mean|refer to)", content, re.I):
            boost += 0.08
    if any(keyword in query for keyword in ("best title", "suitable title", "最佳标题")):
        if re.search(r"(?:best|suitable) title", content, re.I):
            boost += 0.05
    return boost


def retrieve_chunks(
    question: str,
    course_id: int | None = None,
    top_k: int | None = None,
    collection_name: str | None = None,
) -> list[dict]:
    settings = get_settings()
    limit = top_k or settings.retrieval_top_k
    collection = get_chroma_collection(collection_name)
    collection_count = collection.count()
    if collection_count <= 0:
        return []

    candidate_count = min(
        collection_count,
        max(limit, limit * max(1, settings.retrieval_candidate_multiplier)),
    )
    where = {"course_id": course_id} if course_id is not None else None
    results = collection.query(
        query_texts=[question],
        n_results=candidate_count,
        where=where,
    )

    candidates: list[dict] = []
    docs = results.get("documents", [[]])[0]
    distances = results.get("distances", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    for content, distance, metadata in zip(docs, distances, metadatas):
        metadata = metadata or {}
        raw_score = 1.0 - float(distance) if distance is not None else 0.0
        if _quality_flags(metadata) & _EXCLUDED_QUALITY_FLAGS:
            continue
        rerank_score = min(1.0, raw_score + _query_boost(question, content, metadata))
        if rerank_score < settings.retrieval_min_score:
            continue
        candidates.append(
            {
                "content": content,
                "score": round(rerank_score, 4),
                "raw_score": round(raw_score, 4),
                "metadata": metadata,
            }
        )
    candidates.sort(key=lambda item: item["score"], reverse=True)

    items: list[dict] = []
    material_counts: Counter[str] = Counter()
    document_counts: Counter[str] = Counter()
    for item in candidates:
        metadata = item["metadata"]
        material_id = str(metadata.get("material_id") or "").strip()
        document_id = str(metadata.get("document_id") or "").strip()
        if material_id and material_counts[material_id] >= settings.retrieval_max_per_material:
            continue
        if document_id and document_counts[document_id] >= settings.retrieval_max_per_document:
            continue
        items.append(item)
        if material_id:
            material_counts[material_id] += 1
        if document_id:
            document_counts[document_id] += 1
        if len(items) >= limit:
            break
    return items
