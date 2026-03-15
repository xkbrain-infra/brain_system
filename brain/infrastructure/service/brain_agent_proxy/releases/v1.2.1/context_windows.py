"""context_windows.py — 从 context_windows.json 加载模型 context window 配置。"""
import json
from pathlib import Path
from typing import Optional

_JSON_PATH = Path(__file__).parent / "context_windows.json"

def _load() -> dict:
    with open(_JSON_PATH, encoding="utf-8") as f:
        return json.load(f).get("providers", {})

# 启动时加载一次；热更新可调用 reload()
_PROVIDERS: dict = _load()


def reload() -> None:
    """重新从磁盘加载（无需重启进程）。"""
    global _PROVIDERS
    _PROVIDERS = _load()


def get_context_window(model_id: str, provider_id: Optional[str] = None) -> Optional[int]:
    """
    查找模型的 context window（tokens）。
    查找顺序:
      1. providers[provider_id][model_id]
      2. providers[*][model_id]  (遍历所有 provider 取第一个匹配)
      3. model_id 含 "/" 前缀时剥离后重试
    """
    model = str(model_id or "").strip()
    provider = str(provider_id or "").strip().lower()

    def _ctx(entry: dict) -> Optional[int]:
        v = entry.get("context")
        return int(v) if v is not None else None

    # 1. 指定 provider
    if provider and provider in _PROVIDERS:
        models = _PROVIDERS[provider]
        if model in models:
            return _ctx(models[model])

    # 2. 遍历所有 provider fallback
    for pdata in _PROVIDERS.values():
        if not isinstance(pdata, dict):
            continue
        if model in pdata:
            result = _ctx(pdata[model])
            if result is not None:
                return result

    # 3. model_id 本身含 "provider/" 前缀
    if "/" in model:
        bare = model.split("/", 1)[1]
        return get_context_window(bare, provider_id)

    return None
