# context_windows.py
# 各 provider 模型的 context window 大小（tokens）
# 格式: "provider/model-id" 或 "model-id"（作为 fallback）
# 来源: 各 provider 官方文档/API
#
# 查找顺序: provider/model → model (fallback)
from typing import Dict, Optional

MODEL_CONTEXT_WINDOWS: Dict[str, int] = {

    # =========================================================================
    # Copilot (GitHub Copilot proxy, context sizes from Copilot model list)
    # =========================================================================
    "copilot/claude-sonnet-4":              144000,
    "copilot/claude-sonnet-4.5":            160000,
    "copilot/claude-sonnet-4.6":            160000,
    "copilot/claude-opus-4.5":              160000,
    "copilot/claude-opus-4.6":              192000,
    "copilot/claude-haiku-4.5":             160000,
    "copilot/claude-haiku-4-5-20251001":    160000,
    "copilot/gemini-2.5-pro":               173000,
    "copilot/gemini-3-flash":               173000,
    "copilot/gemini-3-pro":                 173000,
    "copilot/gemini-3.1-pro":               173000,
    "copilot/gpt-4.1":                      128000,
    "copilot/gpt-4o":                        68000,
    "copilot/gpt-4o-mini":                  128000,
    "copilot/gpt-5-mini":                   192000,
    "copilot/gpt-5.1":                      192000,
    "copilot/gpt-5.1-codex":               256000,
    "copilot/gpt-5.1-codex-max":           256000,
    "copilot/gpt-5.1-codex-mini":          256000,
    "copilot/gpt-5.2":                      192000,
    "copilot/gpt-5.2-codex":               400000,
    "copilot/gpt-5.3-codex":               400000,
    "copilot/gpt-5.4":                      400000,
    "copilot/grok-code-fast-1":             173000,

    # =========================================================================
    # Claude (Anthropic native API)
    # =========================================================================
    "claude/claude-sonnet-4":               200000,
    "claude/claude-sonnet-4-5":             200000,
    "claude/claude-sonnet-4.5":             200000,
    "claude/claude-sonnet-4-6":             200000,
    "claude/claude-sonnet-4.6":             200000,
    "claude/claude-opus-4-5":               200000,
    "claude/claude-opus-4.5":               200000,
    "claude/claude-opus-4-6":               200000,
    "claude/claude-opus-4.6":               200000,
    "claude/claude-haiku-4-5":              200000,
    "claude/claude-haiku-4.5":              200000,
    "claude/claude-haiku-4-5-20251001":     200000,

    # =========================================================================
    # Alibaba (kimi-k2.5 via Alibaba gateway)
    # =========================================================================
    "alibaba/kimi-k2.5":                    262144,

    # =========================================================================
    # MiniMax (platform.minimax.io)
    # =========================================================================
    "minimax/MiniMax-M2.5":                 204800,
    "minimax/MiniMax-M2.5-highspeed":       204800,
    "minimax/MiniMax-M2.1":                 204800,
    "minimax/MiniMax-M2.1-highspeed":       204800,
    "minimax/MiniMax-M2":                   204800,

    # =========================================================================
    # GLM (Zhipu AI / 智谱)
    # =========================================================================
    "zhipu/glm-5":                          202752,
    "zhipu/glm-4.7":                        169984,
    "zhipu/glm-4.6":                        169984,
    "zhipu/glm-4.5":                        131072,
    "zhipu/glm-4.5-air":                     98304,

    # =========================================================================
    # Qwen (Alibaba Cloud / 阿里云百炼)
    # =========================================================================
    "qwen/qwen3-coder-plus":               1000000,

    # =========================================================================
    # Doubao (ByteDance / 字节跳动)
    # =========================================================================
    "doubao/doubao-1.5-thinking-vision-pro": 128000,

    # =========================================================================
    # Fallback: bare model names (no provider prefix)
    # 当 provider 未知或未配置时使用
    # =========================================================================
    # Claude
    "claude-sonnet-4":              200000,
    "claude-sonnet-4-5":            200000,
    "claude-sonnet-4.5":            200000,
    "claude-sonnet-4-6":            200000,
    "claude-sonnet-4.6":            200000,
    "claude-opus-4-5":              200000,
    "claude-opus-4.5":              200000,
    "claude-opus-4-6":              200000,
    "claude-opus-4.6":              200000,
    "claude-haiku-4-5":             200000,
    "claude-haiku-4.5":             200000,
    "claude-haiku-4-5-20251001":    200000,
    # Kimi
    "kimi-k2.5":                    262144,
    # Qwen
    "qwen3-coder-plus":            1000000,
    # Doubao
    "doubao-1.5-thinking-vision-pro": 128000,
    # GPT
    "gpt-4.1":                      128000,
    "gpt-4o":                       128000,
    "gpt-4o-mini":                  128000,
    "gpt-5-mini":                   192000,
    "gpt-5.1":                      192000,
    "gpt-5.1-codex":                256000,
    "gpt-5.1-codex-max":            256000,
    "gpt-5.1-codex-mini":           256000,
    "gpt-5.2":                      192000,
    "gpt-5.2-codex":                400000,
    "gpt-5.3-codex":                400000,
    "gpt-5.4":                      400000,
    # Gemini
    "gemini-2.5-pro":               173000,
    "gemini-3-flash":               173000,
    "gemini-3-pro":                 173000,
    "gemini-3.1-pro":               173000,
    # Grok
    "grok-code-fast-1":             173000,
    # MiniMax
    "MiniMax-M2.5":                 204800,
    "MiniMax-M2.5-highspeed":       204800,
    "MiniMax-M2.1":                 204800,
    "MiniMax-M2.1-highspeed":       204800,
    "MiniMax-M2":                   204800,
    # GLM
    "glm-5":                        202752,
    "glm-4.7":                      169984,
    "glm-4.6":                      169984,
    "glm-4.5":                      131072,
    "glm-4.5-air":                   98304,
}


def get_context_window(model_id: str, provider_id: Optional[str] = None) -> Optional[int]:
    """
    查找模型的 context window。
    查找顺序:
      1. provider/model  (精确匹配)
      2. model           (fallback，忽略 provider)
      3. 剥离 model_id 中已有的 provider 前缀后再 fallback
    """
    model = str(model_id or "").strip()
    provider = str(provider_id or "").strip().lower()

    # 1. provider/model 精确匹配
    if provider:
        key = f"{provider}/{model}"
        if key in MODEL_CONTEXT_WINDOWS:
            return MODEL_CONTEXT_WINDOWS[key]
        key_lower = f"{provider}/{model.lower()}"
        if key_lower in MODEL_CONTEXT_WINDOWS:
            return MODEL_CONTEXT_WINDOWS[key_lower]

    # 2. bare model（区分大小写后 lowercase fallback）
    if model in MODEL_CONTEXT_WINDOWS:
        return MODEL_CONTEXT_WINDOWS[model]
    if model.lower() in MODEL_CONTEXT_WINDOWS:
        return MODEL_CONTEXT_WINDOWS[model.lower()]

    # 3. model_id 本身含 provider 前缀（如 "copilot/gpt-5.4"）
    if "/" in model:
        bare = model.split("/", 1)[1]
        if bare in MODEL_CONTEXT_WINDOWS:
            return MODEL_CONTEXT_WINDOWS[bare]
        if bare.lower() in MODEL_CONTEXT_WINDOWS:
            return MODEL_CONTEXT_WINDOWS[bare.lower()]

    return None
