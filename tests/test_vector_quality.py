from types import SimpleNamespace

from app.rag import retriever
from app.rag.splitter import _split_tail_answer_text
from app.storage.vectorstore import sanitize_embedding_text


def test_split_tail_answer_accepts_colon():
    question, answer = _split_tail_answer_text("1. 题目正文\n参考答案：\n1. A")
    assert question == "1. 题目正文"
    assert answer == "1. A"


def test_sanitize_embedding_text_removes_raw_image_paths():
    raw = r"题干 [IMAGE_12:data\extracted_images\paper\rId44.wmf] 后续 rId44"
    cleaned = sanitize_embedding_text(raw, max_chars=0)
    assert "extracted_images" not in cleaned
    assert "rId44" not in cleaned
    assert "[图片/公式]" in cleaned


class FakeCollection:
    def count(self):
        return 5

    def query(self, **kwargs):
        return {
            "documents": [["低分", "材料一", "材料一重复", "文档重复", "有效二"]],
            "distances": [[0.55, 0.20, 0.21, 0.22, 0.30]],
            "metadatas": [[
                {"document_id": 1},
                {"document_id": 2, "material_id": "m1", "quality_flags": ""},
                {"document_id": 3, "material_id": "m1", "quality_flags": ""},
                {"document_id": 2, "quality_flags": "fallback_split"},
                {"document_id": 4, "quality_flags": ""},
            ]],
        }


def test_retriever_applies_threshold_quality_filter_and_material_dedup(monkeypatch):
    settings = SimpleNamespace(
        retrieval_top_k=5,
        retrieval_candidate_multiplier=4,
        retrieval_min_score=0.50,
        retrieval_max_per_material=1,
        retrieval_max_per_document=2,
    )
    monkeypatch.setattr(retriever, "get_settings", lambda: settings)
    monkeypatch.setattr(retriever, "get_chroma_collection", lambda name=None: FakeCollection())

    items = retriever.retrieve_chunks("测试", collection_name="math_collection")

    assert [item["content"] for item in items] == ["材料一", "有效二"]
    assert [item["score"] for item in items] == [0.8, 0.7]
