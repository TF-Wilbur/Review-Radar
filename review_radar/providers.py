"""LLM 供应商预设配置"""

PROVIDERS: dict[str, dict] = {
    "OpenAI": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
    },
    "MiniMax": {
        "base_url": "https://api.minimax.chat/v1",
        "default_model": "MiniMax-Text-01",
    },
    "智谱 GLM": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4-flash",
    },
    "Kimi (Moonshot)": {
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-8k",
    },
    "自定义": {
        "base_url": "",
        "default_model": "",
    },
}


def list_provider_names() -> list[str]:
    """返回所有供应商名称"""
    return list(PROVIDERS.keys())


def get_provider(name: str) -> dict:
    """获取供应商配置"""
    return PROVIDERS.get(name, PROVIDERS["自定义"])


def fetch_models(api_key: str, base_url: str) -> list[str]:
    """调用 GET /v1/models 获取可用模型列表"""
    import httpx

    try:
        resp = httpx.get(
            f"{base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        models = data.get("data", [])
        return sorted([m.get("id", "") for m in models if m.get("id")])
    except Exception:
        return []
