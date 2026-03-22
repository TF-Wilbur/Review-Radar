"""LLM 客户端封装 — 支持多供应商 OpenAI 兼容接口"""

import logging
import time
from functools import lru_cache

from openai import OpenAI

from review_radar.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

logger = logging.getLogger("review_radar.llm")

# ── 运行时覆盖（Web UI 动态配置用）──
_runtime_overrides: dict[str, str] = {}


def set_runtime_config(api_key: str = "", base_url: str = "", model: str = ""):
    """Web UI 调用：运行时覆盖 LLM 配置"""
    if api_key:
        _runtime_overrides["api_key"] = api_key
    if base_url:
        _runtime_overrides["base_url"] = base_url
    if model:
        _runtime_overrides["model"] = model


def clear_runtime_config():
    """清除运行时覆盖"""
    _runtime_overrides.clear()


@lru_cache(maxsize=8)
def _cached_client(api_key: str, base_url: str) -> OpenAI:
    """按 (api_key, base_url) 缓存 Client 实例"""
    return OpenAI(api_key=api_key, base_url=base_url)


def get_client(api_key: str = "", base_url: str = "") -> OpenAI:
    """获取 LLM 客户端（优先级：参数 > 运行时覆盖 > .env 配置）"""
    key = api_key or _runtime_overrides.get("api_key", "") or LLM_API_KEY
    url = base_url or _runtime_overrides.get("base_url", "") or LLM_BASE_URL
    return _cached_client(key, url)


def get_model(model: str = "") -> str:
    """获取模型名（优先级：参数 > 运行时覆盖 > .env 配置）"""
    return model or _runtime_overrides.get("model", "") or LLM_MODEL


def check_health(api_key: str = "", base_url: str = "", model: str = "") -> tuple[bool, str]:
    """验证 LLM 连通性，返回 (成功, 消息)"""
    try:
        client = get_client(api_key, base_url)
        m = get_model(model)
        resp = client.chat.completions.create(
            model=m,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=5,
        )
        if resp.choices and resp.choices[0].message.content:
            return True, "连接成功"
        return False, "API 返回空响应"
    except Exception as e:
        return False, f"连接失败: {e}"


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
                logger.warning("LLM 调用失败 (第 %d 次)，%ds 后重试: %s", attempt + 1, wait, e)
                time.sleep(wait)
                continue
            raise
