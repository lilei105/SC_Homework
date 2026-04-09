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
    enable_thinking: bool = False,
) -> str:
    """Synchronous chat completion."""
    client = get_llm_client()
    model = _settings.llm_model

    mode = "thinking" if enable_thinking else "direct"
    logger.info(f"[LLM] Calling {model} ({mode})")
    t0 = time.time()

    if enable_thinking:
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
                if chunk.usage:
                    logger.info(f"[LLM] Token usage: prompt={chunk.usage.prompt_tokens}, completion={chunk.usage.completion_tokens}, total={chunk.usage.total_tokens}")
                continue

            delta = chunk.choices[0].delta

            if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                reasoning_content += delta.reasoning_content

            if hasattr(delta, "content") and delta.content:
                answer_content += delta.content

        elapsed = time.time() - t0

        if reasoning_content:
            reasoning_preview = reasoning_content[:300].replace("\n", " ")
            logger.info(f"[LLM] Thinking ({len(reasoning_content)} chars, {elapsed:.1f}s): {reasoning_preview}...")
        else:
            logger.info(f"[LLM] No thinking content ({elapsed:.1f}s)")

        logger.info(f"[LLM] Answer ({len(answer_content)} chars): {answer_content[:200]}...")

        return answer_content

    else:
        # Direct call, no thinking
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body={"enable_thinking": False},
        )

        elapsed = time.time() - t0
        answer_content = response.choices[0].message.content.strip()

        if hasattr(response, 'usage') and response.usage:
            logger.info(f"[LLM] Token usage: prompt={response.usage.prompt_tokens}, completion={response.usage.completion_tokens}, total={response.usage.total_tokens}")

        logger.info(f"[LLM] Answer ({len(answer_content)} chars, {elapsed:.1f}s): {answer_content[:200]}...")

        return answer_content


def chat_completion_stream(
    messages: List[dict],
    temperature: float = 0.7,
    max_tokens: int = 2048,
    enable_thinking: bool = True,
):
    """Streaming chat completion with thinking mode enabled."""
    client = get_llm_client()
    model = _settings.llm_model

    logger.info(f"[LLM] Calling {model} (stream, thinking={'on' if enable_thinking else 'off'})")

    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
        stream_options={"include_usage": True},
        extra_body={"enable_thinking": enable_thinking},
    )

    reasoning_content = ""
    is_answering = False

    for chunk in stream:
        if not chunk.choices:
            if chunk.usage:
                logger.info(f"[LLM] Token usage: prompt={chunk.usage.prompt_tokens}, completion={chunk.usage.completion_tokens}, total={chunk.usage.total_tokens}")
            continue

        delta = chunk.choices[0].delta

        if hasattr(delta, "reasoning_content") and delta.reasoning_content:
            reasoning_content += delta.reasoning_content

        if hasattr(delta, "content") and delta.content:
            if not is_answering:
                if reasoning_content:
                    reasoning_preview = reasoning_content[:300].replace("\n", " ")
                    logger.info(f"[LLM] Thinking done ({len(reasoning_content)} chars): {reasoning_preview}...")
                is_answering = True
            yield delta.content


async def chat_completion_async(
    messages: List[dict],
    temperature: float = 0.7,
    max_tokens: int = 2048,
    enable_thinking: bool = False,
) -> str:
    """Async wrapper for chat completion."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: chat_completion(messages, temperature, max_tokens, enable_thinking)
    )


def rewrite_query(user_query: str) -> List[str]:
    """Rewrite user query into multiple retrieval-friendly queries.

    Returns:
        List of query strings (1 rewritten + 2 alternatives).
        Falls back to [original_query] on any error.
    """
    from app.core.prompts import QUERY_REWRITE_PROMPT
    import json as _json

    prompt = QUERY_REWRITE_PROMPT.format(user_query=user_query)
    try:
        response = chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=256,
        )
        # Strip markdown code block if present
        text = response.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0]

        data = _json.loads(text)
        queries = [data["rewritten"]] + data.get("alternatives", [])
        if not queries:
            return [user_query]
        logger.info(f"[QueryRewrite] '{user_query}' → {queries}")
        return queries
    except Exception as e:
        logger.warning(f"[QueryRewrite] Failed: {e}, using original query")
        return [user_query]


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
        max_tokens=2048,
        enable_thinking=True,
    )
