import logging
import time
from openai import OpenAI
from app.core.config import get_settings
from typing import Optional, List
import asyncio

logger = logging.getLogger(__name__)

_settings = get_settings()

_client: Optional[OpenAI] = None


def get_llm_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=_settings.dashscope_api_key,
            base_url=_settings.dashscope_base_url
        )
    return _client


def chat_completion(
    messages: List[dict],
    temperature: float = 0.7,
    max_tokens: int = 2048,
) -> str:
    """Synchronous chat completion with thinking mode enabled."""
    client = get_llm_client()
    model = _settings.llm_model

    logger.info(f"[LLM] Calling {model} (non-stream, thinking enabled)")
    t0 = time.time()

    # Use streaming to capture reasoning content
    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
        stream_options={"include_usage": True},
        extra_body={"enable_thinking": True},
    )

    reasoning_content = ""
    answer_content = ""

    for chunk in stream:
        if not chunk.choices:
            # Usage info
            if chunk.usage:
                logger.info(f"[LLM] Token usage: prompt={chunk.usage.prompt_tokens}, completion={chunk.usage.completion_tokens}, total={chunk.usage.total_tokens}")
            continue

        delta = chunk.choices[0].delta

        # Collect reasoning
        if hasattr(delta, "reasoning_content") and delta.reasoning_content:
            reasoning_content += delta.reasoning_content

        # Collect answer
        if hasattr(delta, "content") and delta.content:
            answer_content += delta.content

    elapsed = time.time() - t0

    # Log reasoning summary
    if reasoning_content:
        reasoning_preview = reasoning_content[:300].replace("\n", " ")
        logger.info(f"[LLM] Thinking ({len(reasoning_content)} chars, {elapsed:.1f}s): {reasoning_preview}...")
    else:
        logger.info(f"[LLM] No thinking content ({elapsed:.1f}s)")

    logger.info(f"[LLM] Answer ({len(answer_content)} chars): {answer_content[:200]}...")

    return answer_content


def chat_completion_stream(
    messages: List[dict],
    temperature: float = 0.7,
    max_tokens: int = 2048
):
    """Streaming chat completion with thinking mode enabled."""
    client = get_llm_client()
    model = _settings.llm_model

    logger.info(f"[LLM] Calling {model} (stream, thinking enabled)")

    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
        stream_options={"include_usage": True},
        extra_body={"enable_thinking": True},
    )

    reasoning_content = ""
    is_answering = False

    for chunk in stream:
        if not chunk.choices:
            if chunk.usage:
                logger.info(f"[LLM] Token usage: prompt={chunk.usage.prompt_tokens}, completion={chunk.usage.completion_tokens}, total={chunk.usage.total_tokens}")
            continue

        delta = chunk.choices[0].delta

        # Collect and log reasoning
        if hasattr(delta, "reasoning_content") and delta.reasoning_content:
            reasoning_content += delta.reasoning_content

        # Start yielding answer content
        if hasattr(delta, "content") and delta.content:
            if not is_answering:
                # Log reasoning summary before first answer token
                if reasoning_content:
                    reasoning_preview = reasoning_content[:300].replace("\n", " ")
                    logger.info(f"[LLM] Thinking done ({len(reasoning_content)} chars): {reasoning_preview}...")
                is_answering = True
            yield delta.content


async def chat_completion_async(
    messages: List[dict],
    temperature: float = 0.7,
    max_tokens: int = 2048
) -> str:
    """Async wrapper for chat completion."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: chat_completion(messages, temperature, max_tokens)
    )


def rewrite_query(user_query: str) -> str:
    """Rewrite user query for better retrieval."""
    from app.core.prompts import QUERY_REWRITE_PROMPT

    prompt = QUERY_REWRITE_PROMPT.format(user_query=user_query)
    response = chat_completion(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=256
    )

    return response.strip()


def generate_answer_stream(query: str, context: str):
    """Generate answer with streaming."""
    from app.core.prompts import ANSWER_GENERATION_PROMPT

    prompt = ANSWER_GENERATION_PROMPT.format(
        context=context,
        user_query=query
    )

    yield from chat_completion_stream(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=2048
    )
