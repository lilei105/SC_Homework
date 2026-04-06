from openai import OpenAI
from app.core.config import get_settings
from typing import Optional, List
import asyncio

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
    """Synchronous chat completion."""
    client = get_llm_client()

    response = client.chat.completions.create(
        model=_settings.llm_model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    return response.choices[0].message.content


def chat_completion_stream(
    messages: List[dict],
    temperature: float = 0.7,
    max_tokens: int = 2048
):
    """Streaming chat completion."""
    client = get_llm_client()

    response = client.chat.completions.create(
        model=_settings.llm_model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )

    for chunk in response:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


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
