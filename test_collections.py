import pytest

from app.storage.collections import resolve_collection_name


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        ("语文", "chinese_collection"),
        ("数学", "math_collection"),
        ("英语", "english_collection"),
        ("chinese", "chinese_collection"),
        ("yuwen", "chinese_collection"),
        ("math", "math_collection"),
        ("shuxue", "math_collection"),
        ("english", "english_collection"),
        ("yingyu", "english_collection"),
    ],
)
def test_resolve_subject_collection(subject, expected):
    assert resolve_collection_name(subject=subject) == expected


def test_invalid_collection_name_rejected():
    with pytest.raises(ValueError):
        resolve_collection_name(collection_name="中文库")
