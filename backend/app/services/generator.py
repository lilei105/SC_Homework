from app.services.llm_client import generate_answer_stream
from app.core.prompts import ANSWER_GENERATION_PROMPT
from typing import List, Dict, Any, Generator, Tuple


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


def build_page_to_context_map(contexts: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    """Build a mapping from every page number to its context info."""
    page_map = {}
    for ctx in contexts:
        page_start = ctx.get('page_start')
        page_end = ctx.get('page_end', page_start)
        if page_start is None:
            continue

        chunk_id = ctx.get('chunk_ids', [ctx.get('chunk_id')])[0] if ctx.get('chunk_ids') else ctx.get('chunk_id')
        content = ctx.get('content', '')

        # Map every page in the range
        for page in range(page_start, (page_end or page_start) + 1):
            page_map[page] = {
                'chunk_id': chunk_id,
                'content': content,
                'section_title': ctx.get('section_title', ''),
                'page_start': page_start,
                'page_end': page_end,
            }

    return page_map


def extract_citations(text: str) -> List[int]:
    """Extract page numbers from [Page X] patterns in text."""
    import re
    pages = []
    for match in re.finditer(r'\[Page\s+(\d+)\]', text):
        page = int(match.group(1))
        if page not in pages:
            pages.append(page)
    return pages


def generate_answer(
    query: str,
    contexts: List[Dict[str, Any]]
) -> Generator[Tuple[str, List[Dict[str, Any]]], None, None]:
    """
    Generate answer with streaming and citations.

    Yields:
        Tuple of (token, citations) where citations is updated list
    """
    context_str = format_context(contexts)
    page_to_ctx = build_page_to_context_map(contexts)

    accumulated_text = ""
    citations: List[Dict[str, Any]] = []
    seen_pages: List[int] = []

    for token in generate_answer_stream(query, context_str):
        accumulated_text += token

        # Check for new citations
        cited_pages = extract_citations(accumulated_text)
        for page in cited_pages:
            if page not in seen_pages:
                seen_pages.append(page)
                ctx_info = page_to_ctx.get(page, {})
                citations.append({
                    'page': page,
                    'chunk_id': ctx_info.get('chunk_id'),
                    'content': ctx_info.get('content'),
                    'section_title': ctx_info.get('section_title', ''),
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
