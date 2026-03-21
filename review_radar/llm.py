"""LLM 客户端封装 — 支持 MiniMax / OpenAI 兼容接口"""

import os
import json
from openai import OpenAI


def get_client() -> OpenAI:
    """获取 LLM 客户端"""
    api_key = os.environ.get("LLM_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
    base_url = os.environ.get("LLM_BASE_URL", "https://api.minimax.chat/v1")
    return OpenAI(api_key=api_key, base_url=base_url)


def get_model() -> str:
    """获取模型名"""
    return os.environ.get("LLM_MODEL", "MiniMax-Text-01")


def chat(messages: list[dict], tools: list[dict] | None = None, max_tokens: int = 4096) -> dict:
    """统一的 chat 调用，返回标准化结果"""
    client = get_client()
    model = get_model()

    kwargs = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    response = client.chat.completions.create(**kwargs)
    return response


def chat_simple(prompt: str, system: str = "", max_tokens: int = 4096, retries: int = 3) -> str:
    """简单的单轮对话，返回文本。自动重试 + 指数退避"""
    import time

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    for attempt in range(retries):
        try:
            response = chat(messages, max_tokens=max_tokens)
            return response.choices[0].message.content or ""
        except Exception as e:
            if attempt < retries - 1:
                wait = 2 ** attempt
                print(f"[llm] 调用失败 (第 {attempt + 1} 次)，{wait}s 后重试: {e}")
                time.sleep(wait)
                continue
            raise
