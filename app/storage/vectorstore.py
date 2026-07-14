from functools import lru_cache
import os
import re
from typing import Any

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

from app.core.config import get_settings

_IMAGE_TOKEN_RX = re.compile(r"\[IMAGE_\d+(?::[^\]]*)?\]", re.I)
_FORMULA_TOKEN_RX = re.compile(r"\[FORMULA:([^\]]+)\]", re.I)
_RAW_IMAGE_PATH_RX = re.compile(
    r"(?:[A-Za-z]:)?[^\s\[\]]*data[\\/]extracted_images[\\/][^\]\n]+(?:\.(?:wmf|emf|png|jpe?g|gif|webp|svg))?",
    re.I,
)
_RELATIONSHIP_ID_RX = re.compile(r"\b(?:rId|IMAGE_)\d+\b", re.I)


def sanitize_embedding_text(text: str, max_chars: int | None = None) -> str:
    settings = get_settings()
    value = str(text or "")
    value = _FORMULA_TOKEN_RX.sub(lambda match: match.group(1).strip() or "[公式]", value)
    value = _IMAGE_TOKEN_RX.sub("[图片/公式]", value)
    value = _RAW_IMAGE_PATH_RX.sub("[图片/公式]", value)
    value = _RELATIONSHIP_ID_RX.sub("", value)
    value = re.sub(r"(?:\[图片/公式\]\s*){2,}", "[图片/公式] ", value)
    value = re.sub(r"\s+", " ", value).strip()
    limit = max_chars or settings.embedding_max_chars
    if limit > 0 and len(value) > limit:
        value = value[:limit].rstrip() + "…"
    return value


class LocalSentenceTransformerEmbedding:
    def __init__(self, model_name: str, max_seq_length: int, max_chars: int):
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self.max_chars = max_chars
        self.model = SentenceTransformer(model_name, device="cpu")
        model_limit = int(getattr(self.model, "max_seq_length", max_seq_length) or max_seq_length)
        self.model.max_seq_length = min(max_seq_length, model_limit) if model_limit > 0 else max_seq_length

    def name(self) -> str:
        return f"local-{self.model_name}-{self.model.max_seq_length}"

    def __call__(self, input: list[str]) -> list[list[float]]:
        texts = [sanitize_embedding_text(text, self.max_chars) for text in input]
        return self.model.encode(texts, batch_size=1, normalize_embeddings=True).tolist()

    def embed_documents(self, input: list[str]) -> list[list[float]]:
        return self(input)

    def embed_query(self, input: list[str]) -> list[list[float]]:
        return self(input)


class OpenAICompatibleEmbedding:
    def __init__(self, api_key: str, base_url: str, model: str, max_chars: int):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.max_chars = max_chars

    def name(self) -> str:
        return f"openai-{self.model}"

    def __call__(self, input: list[str]) -> list[list[float]]:
        texts = [sanitize_embedding_text(text, self.max_chars) for text in input]
        response = self.client.embeddings.create(model=self.model, input=texts)
        return [item.embedding for item in response.data]

    def embed_documents(self, input: list[str]) -> list[list[float]]:
        return self(input)

    def embed_query(self, input: list[str]) -> list[list[float]]:
        return self(input)


@lru_cache(maxsize=1)
def get_embedding_function() -> Any:
    settings = get_settings()
    if settings.embedding_provider.lower() == "openai":
        if not settings.openai_api_key:
            raise ValueError("EMBEDDING_PROVIDER=openai requires OPENAI_API_KEY")
        return OpenAICompatibleEmbedding(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.embedding_model,
            max_chars=settings.embedding_max_chars,
        )
    return LocalSentenceTransformerEmbedding(
        settings.local_embedding_model,
        max_seq_length=settings.local_embedding_max_seq_length,
        max_chars=settings.embedding_max_chars,
    )


@lru_cache
def get_chroma_collection(collection_name: str | None = None):
    import chromadb

    settings = get_settings()
    client = chromadb.PersistentClient(path=str(settings.chroma_dir))
    return client.get_or_create_collection(
        name=collection_name or settings.chroma_collection,
        embedding_function=get_embedding_function(),
        metadata={"hnsw:space": "cosine"},
    )


def clear_vectorstore_caches() -> None:
    get_chroma_collection.cache_clear()
    get_embedding_function.cache_clear()
