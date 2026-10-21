"""Vision adapter registry: a model looks at one photo and returns structured tags (Marketing Studio, agency M2).

Switchable per workspace (brand_config.marketing_studio.vision_model, owner only). Same rule as the image registry:
a model is usable only if `enabled` is true, meaning its hosted endpoint has been confirmed and its terms allow
business use. Photos sent to a provider are the workspace's own library photos, resized to at most 1024 px.

| model | provider | endpoint | enabled |
|---|---|---|---|
| gemini-3.6-flash (DEFAULT) | Gemini API, GEMINI_API_KEY | generativelanguage.googleapis.com generateContent (image + text input); same model as concierge_draft | yes |
| gemini-3.1-flash-lite | Gemini API | same endpoint; cheaper, not yet checked with an image | no, until a live request succeeds |
| nvidia-vlm | NVIDIA NIM, NVIDIA_API_KEY | a vision model on integrate.api.nvidia.com; none confirmed yet | no, until a live request succeeds |

Callers use get_model(key) and describe(model, jpeg); describe raises VisionError (transient or not).
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class VisionModel:
    key: str
    label: str
    provider: str
    path: Optional[str]
    enabled: bool
    blocked_reason: Optional[str] = None
    price_in: float = 0.0       # USD per 1M input tokens, for the usage estimate only
    price_out: float = 0.0


DEFAULT_MODEL = "gemini-3.6-flash"

MODELS: dict[str, VisionModel] = {
    "gemini-3.6-flash": VisionModel(key="gemini-3.6-flash", label="Gemini Flash", provider="gemini",
                                    path="gemini-3.6-flash", enabled=True, price_in=0.30, price_out=2.50),
    "gemini-3.1-flash-lite": VisionModel(key="gemini-3.1-flash-lite", label="Gemini Flash Lite (cheaper)",
                                         provider="gemini", path="gemini-3.1-flash-lite", enabled=False,
                                         blocked_reason="Not yet checked with a photo; enable after a live request succeeds.",
                                         price_in=0.10, price_out=0.40),
    "nvidia-vlm": VisionModel(key="nvidia-vlm", label="NVIDIA vision model", provider="nvidia", path=None, enabled=False,
                              blocked_reason="No NVIDIA vision endpoint confirmed yet."),
}


class VisionModelBlocked(Exception):
    pass


class VisionError(Exception):
    def __init__(self, message: str, *, transient: bool):
        super().__init__(message)
        self.transient = transient


def get_model(key: Optional[str]) -> VisionModel:
    model = MODELS.get(key or DEFAULT_MODEL)
    if model is None:
        raise VisionModelBlocked(f"Unknown vision model: {key}")
    if not model.enabled:
        raise VisionModelBlocked(model.blocked_reason or f"{model.label} is not available.")
    return model


def catalogue() -> list[dict]:
    return [{"key": m.key, "label": m.label, "provider": m.provider, "enabled": m.enabled,
             "blocked_reason": m.blocked_reason, "default": m.key == DEFAULT_MODEL} for m in MODELS.values()]


def describe(model: VisionModel, jpeg: bytes, prompt: str) -> tuple[dict, dict]:
    """Return (the model's JSON answer, provenance with token counts). Raises VisionError."""
    if model.provider == "gemini":
        from app.adapters.vision.gemini import describe as gemini_describe
        return gemini_describe(model, jpeg, prompt)
    raise VisionError(f"No vision adapter for provider {model.provider}", transient=False)
