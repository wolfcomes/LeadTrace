"""Compatibility import; shared lifecycle registry lives in the backend package."""
from app.ai_prefill.preview_runtime import PreviewRuntime, PreviewRuntimeError

__all__ = ["PreviewRuntime", "PreviewRuntimeError"]
