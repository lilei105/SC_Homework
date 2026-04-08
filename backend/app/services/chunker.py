"""
文档切分服务 - 整合现有脚本逻辑

处理流程：
1. 解析 Markdown 页面标记
2. 使用 LLM 提取目录结构
3. 构建章节树
4. 分类并切分每个章节
5. 转换为 DocumentSchema 格式
"""
import re
import json
import logging
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
from pathlib import Path

from openai import OpenAI

from app.models.schemas import (
    DocumentSchema, DocumentMetadata, Section, ChunkData,
    PeriodInfo, Entities, Flags, Relations, ParserInfo
)
from app.core.config import get_settings
from app.services.llm_client import chat_completion

logger = logging.getLogger(__name__)


class DocumentChunker:
    """文档切分服务"""

    def __init__(self):
        pass

    def parse_pages(self, markdown_content: str) -> Dict[int, str]:
        """
        解析 Markdown 内容，按页分割

        Args:
            markdown_content: 包含 <!-- PAGE: N --> 标记的内容

        Returns:
            {page_num: page_content}
        """
        pages = re.split(r'<!-- PAGE: (\d+) -->', markdown_content)

        page_dict = {}
        for i in range(1, len(pages), 2):
            page_num = int(pages[i])
            page_content = pages[i + 1] if i + 1 < len(pages) else ""
            page_dict[page_num] = page_content.strip()

        return page_dict

    def extract_first_n_pages(self, page_dict: Dict[int, str], n: int = 5) -> str:
        """提取前 N 页内容"""
        result_parts = []
        for page_num in sorted(page_dict.keys())[:n]:
            result_parts.append(f"<!-- PAGE: {page_num} -->")
            result_parts.append(page_dict[page_num])
        return "\n\n".join(result_parts)

    def generate_document_title(self, page_dict: Dict[int, str]) -> str:
        """
        使用 LLM 从前两页内容生成文档标题

        Returns:
            生成的标题，如 "HSBC Holdings plc Annual Report 2025"
        """
        # 提取前两页
        first_pages = []
        for page_num in sorted(page_dict.keys())[:2]:
            first_pages.append(page_dict[page_num][:2000])  # 每页最多2000字符

        content = "\n\n".join(first_pages)

        system_prompt = """You are a document title generator. Generate a concise and accurate title based on the document content.

Rules:
- Title should include: Company Name + Report Type + Year
- Keep company name in original language (usually English)
- Report types: Annual Report, 10-K, Interim Report, etc.
- Output ONLY the title, nothing else
- Maximum 100 characters"""

        user_prompt = f"""Generate a title for the following document:

---
{content[:4000]}
---

Output the title:"""

        try:
            result = chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                max_tokens=256,
            )

            title = result.strip().strip('"\'')
            logger.info(f"Generated title: {title}")
            return title

        except Exception as e:
            logger.error(f"Failed to generate title: {e}")
            return "Financial Report"

    def check_page_for_toc(self, page_content: str, page_num: int) -> List[Dict[str, Any]]:
        """
        检查单页是否包含目录，如果是则提取目录结构

        Returns:
            目录条目列表，如果这页不是目录则返回空列表
        """
        system_prompt = """You are a document structure analyzer. Determine if this page is a table of contents (TOC) page.

If it is a TOC page, extract the section structure and output JSON:
{
  "is_toc": true,
  "sections": [
    {"title": "Strategic report", "level": 1},
    {"title": "Who we are", "page": 2, "level": 2}
  ]
}

If it is NOT a TOC page, output:
{"is_toc": false, "sections": []}

Rules:
- level 1 = Major sections (titles without page numbers)
- level 2 = Specific section entries (lines with page numbers)
- page is an integer
- Output ONLY JSON, nothing else"""

        user_prompt = f"""Determine if the following content is a table of contents page:

---
{page_content[:4000]}
---

Output JSON:"""

        try:
            result_text = chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                max_tokens=1024,
            )

            # 提取 JSON
            if "```json" in result_text:
                match = re.search(r'```json\s*(.*?)\s*```', result_text, re.DOTALL)
                if match:
                    result_text = match.group(1)
            elif "```" in result_text:
                match = re.search(r'```\s*(.*?)\s*```', result_text, re.DOTALL)
                if match:
                    result_text = match.group(1)

            # Fallback: find raw JSON
            start_idx = result_text.find('{')
            end_idx = result_text.rfind('}')
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                result_text = result_text[start_idx:end_idx+1]

            result = json.loads(result_text)
            is_toc = result.get("is_toc", False)
            sections = result.get("sections", [])

            logger.info(f"Page {page_num}: TOC={is_toc}, sections={len(sections)}")
            return sections if is_toc else []

        except Exception as e:
            logger.error(f"Failed to check page {page_num}: {e}")
            return []

    def extract_toc_with_llm(self, page_dict: Dict[int, str], max_pages: int = 5) -> List[Dict[str, Any]]:
        """
        使用 LLM 逐页检查，找到目录页后提取结构

        优化：一页一页检查，找到目录就停止，避免发送过多内容

        Returns:
            [{"title": "...", "page": 2, "level": 2}, ...]
        """
        sorted_pages = sorted(page_dict.keys())[:max_pages]

        for page_num in sorted_pages:
            sections = self.check_page_for_toc(page_dict[page_num], page_num)
            if sections:
                logger.info(f"Found TOC on page {page_num}: {len(sections)} sections")
                return sections

        logger.info(f"No TOC found in first {len(sorted_pages)} pages")
        return []

    def estimate_tokens(self, text: str) -> int:
        """估算 token 数"""
        if not text:
            return 0
        return max(1, len(text) // 4)

    def build_section_tree(
        self,
        toc_data: List[Dict],
        page_dict: Dict[int, str]
    ) -> List[Dict[str, Any]]:
        """构建章节树"""
        if not toc_data:
            return []

        # 构建章节范围
        section_ranges = []
        for i, section in enumerate(toc_data):
            page = section.get("page")

            # 确定结束页
            next_page = None
            for j in range(i + 1, len(toc_data)):
                next_section = toc_data[j]
                next_level = next_section.get("level", 2)
                current_level = section.get("level", 2)

                if next_level <= current_level and next_section.get("page"):
                    next_page = next_section.get("page")
                    break

            section_ranges.append({
                "title": section.get("title"),
                "level": section.get("level"),
                "page_start": page,
                "page_end": next_page - 1 if next_page else None,
            })

        # 填充最后一个章节的结束页
        max_page = max(page_dict.keys()) if page_dict else 1
        for i in range(len(section_ranges) - 1, -1, -1):
            if section_ranges[i]["page_end"] is None:
                section_ranges[i]["page_end"] = max_page
            else:
                break

        # 提取内容并构建树
        result_sections = []
        current_level1 = None
        level1_children = []

        for sr in section_ranges:
            # 提取页面内容
            content_parts = []
            page_start = sr["page_start"]
            page_end = sr["page_end"]

            if page_start is not None:
                for p in range(page_start, page_end + 1):
                    if p in page_dict:
                        content_parts.append(page_dict[p])

            content = "\n\n".join(content_parts)

            section_item = {
                "title": sr["title"],
                "level": sr["level"],
                "page_start": page_start,
                "page_end": page_end,
                "tokens": self.estimate_tokens(content),
                "content": content
            }

            if sr["level"] == 1:
                # 保存之前的 level1
                if current_level1 is not None:
                    current_level1["children"] = level1_children
                    result_sections.append(current_level1)

                current_level1 = section_item
                level1_children = []
            else:
                level1_children.append(section_item)

        # 保存最后一个 level1
        if current_level1 is not None:
            current_level1["children"] = level1_children
            result_sections.append(current_level1)

        # 计算 level 1 的 tokens
        for s in result_sections:
            s["tokens"] = sum(child.get("tokens", 0) for child in s.get("children", []))
            if s.get("children"):
                s["page_start"] = min(
                    child["page_start"] for child in s["children"]
                    if child.get("page_start") is not None
                )
                s["page_end"] = max(
                    child["page_end"] for child in s["children"]
                    if child.get("page_end") is not None
                )

        return result_sections

    def classify_section(self, section: Dict[str, Any]) -> str:
        """
        分类章节类型

        Returns:
            "narrative" | "table_heavy" | "kpi" | "mixed_media" | "appendix" | "risk_disclosure"
        """
        content = section.get("content", "").lower()
        title = section.get("title", "").lower()

        # 基于 title 分类
        if "risk" in title or "disclosure" in title:
            return "risk_disclosure"
        if "appendix" in title or "supplementary" in title:
            return "appendix"
        if "key performance" in title or "kpi" in title or "financial highlight" in title:
            return "kpi"

        # 基于内容分类
        table_count = content.count("|---") + content.count("| ---")
        if table_count >= 3:
            return "table_heavy"

        if "![image]" in content or "![" in content:
            return "mixed_media"

        return "narrative"

    def chunk_section(
        self,
        section: Dict[str, Any],
        section_type: str,
        section_path: List[str],
        max_tokens: int = 512
    ) -> List[Dict[str, Any]]:
        """
        根据章节类型进行切分

        Returns:
            List of chunk dicts
        """
        content = section.get("content", "")
        tokens = section.get("tokens", 0)
        page_start = section.get("page_start", 1)
        page_end = section.get("page_end", 1)

        chunks = []

        if tokens <= max_tokens:
            # 不需要切分
            chunks.append({
                "section_path": section_path,
                "page_start": page_start,
                "page_end": page_end,
                "content": content,
                "tokens": tokens,
                "chunk_type": section_type
            })
        else:
            # 需要切分 - 按段落切分
            paragraphs = re.split(r'\n\n+', content)
            current_chunk = ""
            current_tokens = 0
            chunk_start_page = page_start

            for para in paragraphs:
                para_tokens = self.estimate_tokens(para)

                if current_tokens + para_tokens > max_tokens and current_chunk:
                    # 保存当前 chunk
                    chunks.append({
                        "section_path": section_path,
                        "page_start": chunk_start_page,
                        "page_end": page_end,  # 简化处理
                        "content": current_chunk.strip(),
                        "tokens": current_tokens,
                        "chunk_type": section_type
                    })
                    current_chunk = para
                    current_tokens = para_tokens
                else:
                    current_chunk += "\n\n" + para if current_chunk else para
                    current_tokens += para_tokens

            # 保存最后一个 chunk
            if current_chunk.strip():
                chunks.append({
                    "section_path": section_path,
                    "page_start": chunk_start_page,
                    "page_end": page_end,
                    "content": current_chunk.strip(),
                    "tokens": current_tokens,
                    "chunk_type": section_type
                })

        return chunks

    def process_markdown(
        self,
        markdown_content: str,
        document_metadata: Dict[str, Any],
        ocr_json_result: Optional[Dict[str, Any]] = None,
        save_intermediate: Optional[Path] = None
    ) -> Tuple[DocumentSchema, Dict[str, Any]]:
        """
        完整的 Markdown 处理流程

        Args:
            markdown_content: OCR 输出的 Markdown
            document_metadata: 文档元数据
            ocr_json_result: 百度 OCR 返回的 JSON 结果（包含页面信息）
            save_intermediate: 保存中间结果的目录路径

        Returns:
            (DocumentSchema, intermediate_results): 文档结构和中间结果
        """
        intermediate = {
            "page_dict": {},
            "toc_data": [],
            "sections": [],
            "chunks_raw": [],
        }

        logger.info("Processing markdown content...")

        # 1. 解析页面 - 优先使用 JSON 结果
        page_dict = {}

        if ocr_json_result and "pages" in ocr_json_result:
            # 使用百度 OCR JSON 结果中的页面信息
            for page in ocr_json_result.get("pages", []):
                page_num = page.get("page_num", 0)
                page_text = page.get("text", "")
                if page_num >= 0 and page_text:
                    page_dict[page_num + 1] = page_text  # 页码从 1 开始
            logger.info(f"Parsed {len(page_dict)} pages from OCR JSON")

        if not page_dict:
            # 回退到 Markdown 页面标记解析
            page_dict = self.parse_pages(markdown_content)
            logger.info(f"Parsed {len(page_dict)} pages from Markdown markers")

        # 如果还是没有页面信息，将整个文档作为单页处理
        if not page_dict:
            page_dict = {1: markdown_content}
            logger.warning("No page markers found, treating as single page")

        intermediate["page_dict"] = {k: v[:200] + "..." if len(v) > 200 else v for k, v in page_dict.items()}

        # 2. 提取目录 (逐页检查，找到即停止)
        toc_data = self.extract_toc_with_llm(page_dict, max_pages=5)
        logger.info(f"Extracted {len(toc_data)} TOC entries")
        intermediate["toc_data"] = toc_data

        # 2.5 生成文档标题（如果没有提供）
        if not document_metadata.get("report_title"):
            document_metadata["report_title"] = self.generate_document_title(page_dict)

        # 3. 构建章节树
        sections = self.build_section_tree(toc_data, page_dict)
        logger.info(f"Built {len(sections)} level-1 sections")
        intermediate["sections"] = sections

        # 如果没有提取到章节，创建一个默认章节
        if not sections:
            logger.warning("No sections extracted, creating default section")
            all_content = "\n\n".join(page_dict.values())
            sections = [{
                "title": "Document Content",
                "level": 1,
                "page_start": 1,
                "page_end": max(page_dict.keys()) if page_dict else 1,
                "tokens": self.estimate_tokens(all_content),
                "content": all_content,
                "children": []
            }]

        # 4. 切分每个章节
        all_chunks = []
        chunk_index = 0

        for level1 in sections:
            level1_title = level1.get("title", "Unknown")

            for level2 in level1.get("children", []):
                section_path = [level1_title, level2.get("title", "")]
                section_type = self.classify_section(level2)

                chunks = self.chunk_section(
                    level2,
                    section_type,
                    section_path
                )

                for chunk in chunks:
                    chunk["chunk_id"] = f"chunk_{chunk_index:04d}"
                    chunk["chunk_index"] = chunk_index
                    chunk_index += 1
                    all_chunks.append(chunk)

        # 如果没有生成 chunks，将所有内容作为一个 chunk
        if not all_chunks:
            all_content = "\n\n".join(page_dict.values())
            all_chunks = [{
                "chunk_id": "chunk_0000",
                "chunk_index": 0,
                "section_path": ["Document Content"],
                "page_start": 1,
                "page_end": max(page_dict.keys()) if page_dict else 1,
                "content": all_content,
                "tokens": self.estimate_tokens(all_content),
                "chunk_type": "narrative"
            }]
            logger.warning("No chunks generated, created single fallback chunk")

        logger.info(f"Generated {len(all_chunks)} chunks")
        intermediate["chunks_raw"] = all_chunks

        # 保存中间结果
        if save_intermediate:
            self._save_intermediate(save_intermediate, intermediate)

        # 5. 转换为 DocumentSchema
        doc_schema = self._build_schema(all_chunks, sections, document_metadata, page_dict)

        return doc_schema, intermediate

    def _save_intermediate(self, path: Path, intermediate: Dict[str, Any]):
        """保存中间结果到文件"""
        import json

        # 保存 TOC
        toc_path = path / "toc.json"
        toc_path.write_text(
            json.dumps(intermediate["toc_data"], ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        logger.info(f"Saved TOC to: {toc_path}")

        # 保存章节树
        sections_path = path / "section_tree.json"
        sections_path.write_text(
            json.dumps(intermediate["sections"], ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        logger.info(f"Saved section tree to: {sections_path}")

        # 保存原始 chunks
        chunks_path = path / "chunks_raw.json"
        chunks_path.write_text(
            json.dumps(intermediate["chunks_raw"], ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        logger.info(f"Saved raw chunks to: {chunks_path}")

    def _build_schema(
        self,
        chunks: List[Dict],
        sections: List[Dict],
        metadata: Dict[str, Any],
        page_dict: Dict[int, str]
    ) -> DocumentSchema:
        """构建最终的 DocumentSchema"""
        # 构建 sections 列表
        schema_sections = []
        section_index = 0

        for level1 in sections:
            level1_id = f"sec_{section_index:04d}"
            section_index += 1

            schema_sections.append(Section(
                section_id=level1_id,
                title=level1.get("title", ""),
                normalized_title=level1.get("title", ""),
                summary=None,
                page_start=level1.get("page_start") or 1,
                page_end=level1.get("page_end") or 1
            ))

            for level2 in level1.get("children", []):
                level2_id = f"sec_{section_index:04d}"
                section_index += 1

                schema_sections.append(Section(
                    section_id=level2_id,
                    title=level2.get("title", ""),
                    normalized_title=level2.get("title", ""),
                    summary=None,
                    page_start=level2.get("page_start") or 1,
                    page_end=level2.get("page_end") or 1
                ))

        # 构建 chunks 列表
        schema_chunks = []
        for i, chunk in enumerate(chunks):
            section_path = chunk.get("section_path", [])
            section_title = " > ".join(section_path) if section_path else "Unknown"

            # 映射 chunk_type
            original_type = chunk.get("chunk_type", "narrative")
            type_mapping = {
                "narrative": "text",
                "table_heavy": "table",
                "kpi": "table",
                "mixed_media": "mixed",
                "appendix": "text",
                "risk_disclosure": "text"
            }

            content = chunk.get("content", "")
            content_brief = content[:200] + "..." if len(content) > 200 else content

            schema_chunks.append(ChunkData(
                chunk_id=chunk.get("chunk_id", f"chunk_{i:04d}"),
                chunk_index=chunk.get("chunk_index", i),
                section_id=f"sec_{i:04d}",
                section_title=section_title,
                section_summary=None,
                page_start=chunk.get("page_start", 1),
                page_end=chunk.get("page_end", 1),
                chunk_type=type_mapping.get(original_type, "text"),
                content=content,
                content_brief=content_brief,
                keywords=[],
                period=None,
                entities=None,
                table_data=None,
                figure_data=None,
                financial_metrics=[],
                source_trace=None,
                relations=Relations(
                    prev_chunk_id=chunks[i-1].get("chunk_id") if i > 0 else None,
                    next_chunk_id=chunks[i+1].get("chunk_id") if i < len(chunks) - 1 else None
                ),
                bundle_id=None,
                flags=Flags(
                    is_key_financial_chunk=original_type in ["kpi", "table_heavy"]
                )
            ))

        # 构建文档元数据
        max_page = max(page_dict.keys()) if page_dict else 1

        doc_metadata = DocumentMetadata(
            document_id=metadata.get("document_id", "unknown"),
            source_file=metadata.get("source_file", "unknown.pdf"),
            company_name=metadata.get("company_name", "Unknown"),
            ticker=metadata.get("ticker"),
            report_type=metadata.get("report_type", "annual_report"),
            report_title=metadata.get("report_title", ""),
            language=metadata.get("language", "en"),
            currency=metadata.get("currency", "USD"),
            fiscal_year=metadata.get("fiscal_year", 2025),
            fiscal_period=metadata.get("fiscal_period", "FY"),
            report_date=metadata.get("report_date"),
            page_count=max_page,
            parser=ParserInfo(
                provider="baidu_paddleocr_vl",
                version="1.0",
                notes="Processed via Baidu PaddleOCR-VL API"
            )
        )

        return DocumentSchema(
            schema_version="1.0",
            document=doc_metadata,
            sections=schema_sections,
            chunks=schema_chunks
        )


# 单例
_chunker: Optional[DocumentChunker] = None


def get_chunker() -> DocumentChunker:
    """获取切分服务实例"""
    global _chunker
    if _chunker is None:
        _chunker = DocumentChunker()
    return _chunker
