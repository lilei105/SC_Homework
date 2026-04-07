"""
Chunk Metadata Extraction Service

Extracts keywords, entities, period, and financial metrics from chunks using LLM.
"""
import json
import logging
import re
from typing import List, Dict, Any, Optional
from openai import OpenAI

from app.core.config import get_settings
from app.core.prompts import CHUNK_METADATA_EXTRACTION_PROMPT

logger = logging.getLogger(__name__)


class MetadataExtractor:
    """Extract metadata from document chunks using LLM"""

    def __init__(self):
        settings = get_settings()
        self.llm_client = OpenAI(
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url
        )
        self.llm_model = settings.llm_model

    def extract_chunk_metadata(
        self,
        content: str,
        section_title: str
    ) -> Dict[str, Any]:
        """
        Extract all metadata for a chunk using single LLM call.

        Returns:
            {
                "keywords": [...],
                "period": {...} or None,
                "entities": {...} or None,
                "financial_metrics": [...]
            }
        """
        # Truncate content if too long
        max_content_len = 4000
        truncated_content = content[:max_content_len]

        prompt = CHUNK_METADATA_EXTRACTION_PROMPT.format(
            section_title=section_title,
            content=truncated_content
        )

        try:
            response = self.llm_client.chat.completions.create(
                model=self.llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )

            result_text = response.choices[0].message.content.strip()

            # Extract JSON from code fences or raw text
            json_text = None

            # Try to extract from code fences first
            if "```json" in result_text:
                match = re.search(r'```json\s*(.*?)\s*```', result_text, re.DOTALL)
                if match:
                    json_text = match.group(1).strip()
            elif "```" in result_text:
                match = re.search(r'```\s*(.*?)\s*```', result_text, re.DOTALL)
                if match:
                    json_text = match.group(1).strip()

            # If no code fences found, try to extract raw JSON
            if json_text is None:
                json_text = result_text.strip()
                # Find the first { and last } to extract just the JSON part
                start_idx = json_text.find('{')
                end_idx = json_text.rfind('}')
                if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                    json_text = json_text[start_idx:end_idx+1]
                else:
                    logger.error(f"No valid JSON found in response: {result_text[:200]}")
                    raise ValueError("No valid JSON in response")

            result = json.loads(json_text)

            # Ensure required structure
            return {
                "keywords": result.get("keywords", []),
                "period": result.get("period"),
                "entities": result.get("entities"),
                "financial_metrics": result.get("financial_metrics", [])
            }

        except Exception as e:
            logger.error(f"Failed to extract metadata: {e}")
            return {
                "keywords": [],
                "period": None,
                "entities": None,
                "financial_metrics": []
            }

    def enrich_chunks_batch(
        self,
        chunks: List[Dict[str, Any]],
        batch_size: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Enrich multiple chunks with metadata.

        Args:
            chunks: List of chunk dicts with 'content' and 'section_title'
            batch_size: Number of chunks to process in parallel (for future optimization)

        Returns:
            List of chunks with added metadata fields
        """
        enriched_chunks = []

        for i, chunk in enumerate(chunks):
            logger.info(f"Enriching chunk {i+1}/{len(chunks)}: {chunk.get('chunk_id', 'unknown')}")

            metadata = self.extract_chunk_metadata(
                content=chunk.get("content", ""),
                section_title=chunk.get("section_title", "")
            )

            # Merge metadata into chunk
            enriched_chunk = {**chunk, **metadata}
            enriched_chunks.append(enriched_chunk)

        return enriched_chunks


# Singleton
_extractor: Optional[MetadataExtractor] = None


def get_metadata_extractor() -> MetadataExtractor:
    """Get metadata extractor instance"""
    global _extractor
    if _extractor is None:
        _extractor = MetadataExtractor()
    return _extractor
