from app.services.llm_client import generate_answer_stream
from app.core.prompts import ANSWER_GENERATION_PROMPT
from typing import List, Dict, Any, Generator, Tuple


def format_context(contexts: List[Dict[str, Any]]) -> str:
    """Format contexts into a string for the LLM."""
    formatted = []

    for i, ctx in enumerate(contexts, 1):
        page_info = f"Page {ctx.get('page_start', '?')}"
        if ctx.get('page_end') and ctx['page_end'] != ctx['page_start']:
            page_info = f"Pages {ctx['page_start']}-{ctx['page_end']}"

        section = ctx.get('section_title', 'Unknown Section')
        content = ctx.get('content', '')

        formatted.append(
            f"---\n[Source {i}: {section} ({page_info})]\n{content}\n---"
        )

    return "\n\n".join(formatted)


def extract_citations(text: str) -> List[Dict[str, Any]]:
    """Extract page citations from generated text."""
    import re
    citations = []

    # Match [Page X] patterns
    pattern = r'\[Page\s+(\d+)\]'
    matches = re.finditer(pattern, text)

    for match in matches:
        page = int(match.group(1))
        if page not in [c['page'] for c in citations]:
            citations.append({
                'page': page,
                'chunk_id': None,  # Will be filled by caller
                'content': None    # Will be filled by caller
            })

    return citations


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

    # Create page to chunk mapping
    page_to_chunk = {}
    for ctx in contexts:
        page = ctx.get('page_start')
        if page:
            page_to_chunk[page] = {
                'chunk_id': ctx.get('chunk_ids', [ctx.get('chunk_id')])[0],
                'content': ctx.get('content')
            }

    accumulated_text = ""
    citations = []

    for token in generate_answer_stream(query, context_str):
        accumulated_text += token

        # Check for new citations
        new_citations = extract_citations(accumulated_text)
        for cit in new_citations:
            if cit['page'] not in [c['page'] for c in citations]:
                # Fill in chunk info
                chunk_info = page_to_chunk.get(cit['page'], {})
                cit['chunk_id'] = chunk_info.get('chunk_id')
                cit['content'] = chunk_info.get('content')
                citations.append(cit)

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
