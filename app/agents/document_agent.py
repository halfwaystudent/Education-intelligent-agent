from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import uuid4

from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.llm import get_chat_llm
from app.models.db import Chunk, Document
from app.rag.ingest import clear_document_index
from app.rag.loaders import load_text_pages
from app.storage.vectorstore import get_chroma_collection


DOCUMENT_AGENT_PROMPT = """你是 document_agent，负责把公司产品文档整理成适合知识库检索的结构化资料。

请严格根据原文处理，不要编造不存在的产品、参数、价格、承诺或功能。

任务：
1. 识别文档中每个产品或产品模块，并按产品拆分内容。
2. 为每个产品补充适合检索的元数据，例如 product_name、category、target_user、features、use_cases、keywords、source_summary。
3. 将零散描述整理成更清晰的文档结构，保留关键事实、限制条件、适用场景、功能卖点。
4. 如果无法判断某项元数据，请使用空字符串或空数组，不要猜测。
5. 只返回合法 JSON，不要返回 Markdown 代码块。

返回格式：
{
  "document_title": "",
  "document_type": "product_document",
  "language": "zh-CN",
  "products": [
    {
      "product_name": "",
      "category": "",
      "target_user": "",
      "features": [],
      "use_cases": [],
      "keywords": [],
      "source_summary": "",
      "content": "整理后的产品说明正文"
    }
  ]
}

原始文件名：{file_name}
原始文档内容：
{content}
"""


class DocumentAgent:
    name = "document_agent"

    def ingest(self, db: Session, document: Document, collection_name: str | None = None, subject: str = "") -> dict:
        settings = get_settings()
        target_collection = collection_name or settings.chroma_collection
        path = Path(document.source_path)
        try:
            clear_document_index(db, document, target_collection)
            pages = load_text_pages(path)
            raw_text = self._pages_to_text(pages)
            if not raw_text:
                raise ValueError("文档未解析出有效文本")

            optimized = self._optimize_document(raw_text, document.file_name)
            chunks = self._split_optimized_document(optimized, raw_text)
            if not chunks:
                raise ValueError("document_agent 未生成有效切片")

            collection = get_chroma_collection(target_collection)
            ids: list[str] = []
            texts: list[str] = []
            metadatas: list[dict] = []
            db_chunks: list[Chunk] = []

            for index, item in enumerate(chunks, start=1):
                chunk_id = f"doc-{target_collection}-{document.id}-{index}-{uuid4().hex[:8]}"
                metadata = {
                    "collection_name": target_collection,
                    "dataset": target_collection,
                    "subject": subject,
                    "agent": self.name,
                    "course_id": document.course_id,
                    "document_id": document.id,
                    "file_name": document.file_name,
                    "page": item.get("page"),
                    "section_title": item.get("section_title", ""),
                    "product_name": item.get("product_name", ""),
                    "category": item.get("category", ""),
                    "target_user": item.get("target_user", ""),
                    "keywords": item.get("keywords", []),
                    "features": item.get("features", []),
                    "use_cases": item.get("use_cases", []),
                    "chunk_type": item.get("chunk_type", "product_document"),
                    "chunk_id": chunk_id,
                    "source_path": document.source_path,
                }
                ids.append(chunk_id)
                texts.append(item.get("embedding_text") or item["content"])
                metadatas.append(self._flatten_metadata(metadata))
                db_chunks.append(
                    Chunk(
                        course_id=document.course_id,
                        document_id=document.id,
                        chunk_id=chunk_id,
                        content=item["content"],
                        page=item.get("page"),
                        section_title=item.get("section_title", ""),
                        metadata_json=metadata,
                    )
                )

            collection.add(ids=ids, documents=texts, metadatas=metadatas)
            db.add_all(db_chunks)
            document.status = "indexed"
            document.error_message = ""
            db.commit()
            return {
                "agent": self.name,
                "collection": target_collection,
                "document_id": document.id,
                "file_name": document.file_name,
                "chunks": len(db_chunks),
                "products": sorted({chunk.metadata_json.get("product_name", "") for chunk in db_chunks if chunk.metadata_json.get("product_name")}),
            }
        except Exception as exc:
            document.status = "failed"
            document.error_message = str(exc)
            db.commit()
            raise

    def _pages_to_text(self, pages: list[dict]) -> str:
        blocks: list[str] = []
        for page in pages:
            text = (page.get("text") or "").strip()
            if not text:
                continue
            page_no = page.get("page")
            prefix = f"[page:{page_no}]\n" if page_no else ""
            blocks.append(prefix + text)
        return "\n\n".join(blocks).strip()

    def _optimize_document(self, raw_text: str, file_name: str) -> dict:
        llm = get_chat_llm()
        if llm is None:
            return self._fallback_optimize(raw_text, file_name)

        max_chars = 18000
        prompt = DOCUMENT_AGENT_PROMPT.format(file_name=file_name, content=raw_text[:max_chars])
        response = llm.invoke(prompt).content
        try:
            return json.loads(self._strip_json_fence(response))
        except json.JSONDecodeError:
            return self._fallback_optimize(raw_text, file_name, note="llm_json_parse_failed")

    def _fallback_optimize(self, raw_text: str, file_name: str, note: str = "no_llm") -> dict:
        title = Path(file_name).stem
        sections = self._split_by_heading(raw_text)
        products = []
        for section_title, section_text in sections:
            product_name = section_title or title
            products.append(
                {
                    "product_name": product_name,
                    "category": "",
                    "target_user": "",
                    "features": self._extract_bullets(section_text),
                    "use_cases": [],
                    "keywords": self._extract_keywords(product_name, section_text),
                    "source_summary": section_text[:300],
                    "content": section_text,
                    "agent_note": note,
                }
            )
        return {"document_title": title, "document_type": "product_document", "language": "zh-CN", "products": products}

    def _split_optimized_document(self, optimized: dict, raw_text: str) -> list[dict]:
        products = optimized.get("products") or []
        if not products:
            optimized = self._fallback_optimize(raw_text, "document.txt", note="empty_products")
            products = optimized.get("products") or []

        settings = get_settings()
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            separators=["\n\n", "\n", "。", "；", ". ", " ", ""],
        )
        chunks: list[dict] = []
        for product in products:
            product_name = str(product.get("product_name") or optimized.get("document_title") or "未命名产品")
            content = self._format_product_content(product)
            for piece_index, piece in enumerate(splitter.split_text(content), start=1):
                if not piece.strip():
                    continue
                keywords = self._ensure_list(product.get("keywords"))
                features = self._ensure_list(product.get("features"))
                use_cases = self._ensure_list(product.get("use_cases"))
                embedding_text = "\n".join(
                    [
                        f"产品名称：{product_name}",
                        f"产品分类：{product.get('category', '')}",
                        f"目标用户：{product.get('target_user', '')}",
                        f"关键词：{'、'.join(keywords)}",
                        f"功能特性：{'、'.join(features)}",
                        f"适用场景：{'、'.join(use_cases)}",
                        piece.strip(),
                    ]
                )
                chunks.append(
                    {
                        "content": piece.strip(),
                        "embedding_text": embedding_text,
                        "page": None,
                        "section_title": f"{product_name}-{piece_index}",
                        "product_name": product_name,
                        "category": str(product.get("category") or ""),
                        "target_user": str(product.get("target_user") or ""),
                        "keywords": keywords,
                        "features": features,
                        "use_cases": use_cases,
                        "chunk_type": "product_document",
                    }
                )
        return chunks

    def _format_product_content(self, product: dict) -> str:
        lines = [
            f"产品名称：{product.get('product_name', '')}",
            f"产品分类：{product.get('category', '')}",
            f"目标用户：{product.get('target_user', '')}",
            f"关键词：{'、'.join(self._ensure_list(product.get('keywords')))}",
            f"功能特性：{'、'.join(self._ensure_list(product.get('features')))}",
            f"适用场景：{'、'.join(self._ensure_list(product.get('use_cases')))}",
            f"内容摘要：{product.get('source_summary', '')}",
            "正文：",
            str(product.get("content") or ""),
        ]
        return "\n".join(line for line in lines if line.strip())

    def _split_by_heading(self, text: str) -> list[tuple[str, str]]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return []
        sections: list[tuple[str, list[str]]] = []
        current_title = ""
        current_lines: list[str] = []
        heading_rx = re.compile(r"^(?:#{1,6}\s*)?(?:产品|模块|方案|服务)?[\u4e00-\u9fa5A-Za-z0-9][\u4e00-\u9fa5A-Za-z0-9\s_-]{1,40}[:：]?$")
        for line in lines:
            is_heading = len(line) <= 48 and bool(heading_rx.match(line)) and not line.endswith(("。", ".", "；", ";"))
            if is_heading and current_lines:
                sections.append((current_title, current_lines))
                current_title = line.rstrip(":：")
                current_lines = []
            elif is_heading and not current_title:
                current_title = line.rstrip(":：")
            else:
                current_lines.append(line)
        if current_lines:
            sections.append((current_title, current_lines))
        if not sections:
            return [("", text)]
        return [(title, "\n".join(body).strip()) for title, body in sections if "\n".join(body).strip()]

    def _extract_bullets(self, text: str) -> list[str]:
        bullets = []
        for line in text.splitlines():
            clean = re.sub(r"^[\-*·\d.、\s]+", "", line).strip()
            if 6 <= len(clean) <= 80:
                bullets.append(clean)
            if len(bullets) >= 8:
                break
        return bullets

    def _extract_keywords(self, product_name: str, text: str) -> list[str]:
        words = [product_name] if product_name else []
        for token in re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]{2,12}", text):
            if token not in words:
                words.append(token)
            if len(words) >= 12:
                break
        return words

    def _ensure_list(self, value) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        return [str(value)] if str(value).strip() else []

    def _flatten_metadata(self, metadata: dict) -> dict:
        flat = {}
        for key, value in metadata.items():
            if value is None:
                flat[key] = ""
            elif isinstance(value, list):
                flat[key] = "；".join(str(item) for item in value)
            elif isinstance(value, dict):
                flat[key] = json.dumps(value, ensure_ascii=False)
            else:
                flat[key] = value
        return flat

    def _strip_json_fence(self, text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        return text.strip()


document_agent = DocumentAgent()
