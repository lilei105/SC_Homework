from app.services.llm_client import generate_answer_stream
from app.core.prompts import ANSWER_GENERATION_PROMPT
from typing import List, Dict, Any, Generator, Tuple
import re


def format_context(contexts: List[Dict[str, Any]]) -> str:
    """Format contexts into a string for the LLM."""
    formatted = []

    for i, ctx in enumerate(contexts, 1):
        page_start = ctx.get('page_start', '?')
        page_end = ctx.get('page_end', page_start)

        if page_start != page_end and page_end != '?':
            page_info = f"Pages {page_start}-{page_end}"
        else:
            page_info = f"Page {page_start}"

        section = ctx.get('section_title', 'Unknown Section')
        content = ctx.get('content', '')

        formatted.append(
            f"---\n[Source {i}: {section} ({page_info})]\n{content}\n---"
        )

    return "\n\n".join(formatted)


def extract_citations(text: str) -> List[int]:
    """Extract source numbers from [Source N] patterns in text."""
    sources = []
    for match in re.finditer(r'\[Source\s+(\d+)\]', text, re.IGNORECASE):
        source_num = int(match.group(1))
        if source_num not in sources:
            sources.append(source_num)
    return sources


def generate_answer(
    query: str,
    contexts: List[Dict[str, Any]]
) -> Generator[Tuple[str, List[Dict[str, Any]]], None, None]:
    """
    Generate answer with streaming and citations.

    Yields:
        Tuple of (token, citations) where citations is updated list.
        Citations use [Source N] format, where N maps directly to the context index.
    """
    context_str = format_context(contexts)
    accumulated_text = ""
    citations: List[Dict[str, Any]] = []
    seen_sources: List[int] = []

    for token in generate_answer_stream(query, context_str):
        accumulated_text += token

        # Check for new citations
        cited_sources = extract_citations(accumulated_text)
        for source_num in cited_sources:
            if source_num not in seen_sources:
                seen_sources.append(source_num)
                # source_num is 1-indexed, contexts list is 0-indexed
                ctx_idx = source_num - 1
                if 0 <= ctx_idx < len(contexts):
                    ctx = contexts[ctx_idx]
                    page_start = ctx.get('page_start')
                    page_end = ctx.get('page_end', page_start)
                    chunk_id = ctx.get('chunk_ids', [ctx.get('chunk_id')])[0] if ctx.get('chunk_ids') else ctx.get('chunk_id')
                    section_title = ctx.get('section_title', '')

                    # Build a readable page label
                    if page_start and page_end and page_start != page_end:
                        page_label = f"Pages {page_start}-{page_end}"
                    elif page_start:
                        page_label = f"Page {page_start}"
                    else:
                        page_label = "Unknown"

                    citations.append({
                        'source_num': source_num,
                        'page_start': page_start,
                        'page_end': page_end,
                        'page_label': page_label,
                        'chunk_id': chunk_id,
                        'content': ctx.get('content', ''),
                        'section_title': section_title,
                    })

        yield token, citations.copy()


def prepare_final_contexts(
    contexts: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Prepare contexts for response, extracting key info."""
    return [
        {
            'chunk_id': ctx.get('chunk_ids', [ctx.get('chunk_id')])[0] if ctx.get('chunk_ids') else ctx.get('chunk_id'),
            'page_start': ctx.get('page_start'),
            'page_end': ctx.get('page_end'),
            'section_title': ctx.get('section_title'),
            'score': ctx.get('rerank_score') or ctx.get('colbert_score') or ctx.get('score'),
        }
        for ctx in contexts
    ]
