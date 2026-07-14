from __future__ import annotations

import re

from app.core.config import get_settings


SUBJECT_COLLECTIONS = {
    "语文": "chinese_collection",
    "中文": "chinese_collection",
    "chinese": "chinese_collection",
    "yuwen": "chinese_collection",
    "数学": "math_collection",
    "math": "math_collection",
    "shuxue": "math_collection",
    "英语": "english_collection",
    "英文": "english_collection",
    "english": "english_collection",
    "yingyu": "english_collection",
}

COLLECTION_SUBJECTS = {
    "chinese_collection": "语文",
    "math_collection": "数学",
    "english_collection": "英语",
}

def normalize_subject(subject: str | None) -> str:
    if not subject:
        return ""
    value = subject.strip()
    return COLLECTION_SUBJECTS.get(SUBJECT_COLLECTIONS.get(value.lower(), ""), value)


def normalize_collection_name(collection_name: str) -> str:
    value = collection_name.strip()
    if not value:
        raise ValueError("collection_name 不能为空")
    if not re.fullmatch(r"[A-Za-z0-9_-]{3,63}", value):
        raise ValueError("collection_name 只能包含 3-63 位英文字母、数字、下划线或中划线")
    return value


def resolve_collection_name(subject: str | None = None, collection_name: str | None = None) -> str:
    if collection_name and collection_name.strip():
        return normalize_collection_name(collection_name)
    if subject and subject.strip():
        key = subject.strip().lower()
        if key in SUBJECT_COLLECTIONS:
            return SUBJECT_COLLECTIONS[key]
        return normalize_collection_name(key)
    return get_settings().chroma_collection
