"""Image-generation adapter registry (Marketing Studio, opt-in per tenant).

Every model is listed with its licence status. A model is usable only if `enabled` is true: commercial use cleared on
the provider's own model page AND a hosted endpoint confirmed against the live API. Checked 18 Oct 2026:

| model | licence on build.nvidia.com | hosted endpoint | enabled |
|---|---|---|---|
| flux.1-schnell | "ready for commercial use" (Apache-2.0) | ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-schnell (live 422 on bad size) | yes |
| qwen-image | "commercial and non-commercial" (Apache-2.0) | not found: guessed paths return 404 | no, until verified |
| stable-diffusion-3.5-large | "ready for non-commercial use"; commercial needs a Stability AI licence | not checked | no: licence |
| flux.1-dev | "non-commercial use only" | n/a | never |

Callers use get_model(key); it raises ImageModelBlocked for anything not enabled, with the reason.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ImageModel:
    key: str
    label: str
    provider: str
    path: Optional[str]                      # provider path, e.g. "black-forest-labs/flux.1-schnell"
    enabled: bool
    licence: str
    blocked_reason: Optional[str] = None
    sizes: dict = field(default_factory=dict)   # shape -> (width, height), only sizes the model accepts
    steps: Optional[int] = None


# Sizes FLUX.1-schnell accepted on a live request (its 422 lists heights 768..1344 in steps of 64).
_FLUX_SIZES = {"square": (1024, 1024), "portrait": (896, 1152), "story": (768, 1344), "landscape": (1344, 768)}

MODELS: dict[str, ImageModel] = {
    "flux.1-schnell": ImageModel(
        key="flux.1-schnell", label="FLUX.1 schnell (fast)", provider="nvidia", path="black-forest-labs/flux.1-schnell",
        enabled=True, licence="Apache-2.0; build.nvidia.com: ready for commercial use", sizes=_FLUX_SIZES, steps=4),
    "qwen-image": ImageModel(
        key="qwen-image", label="Qwen-Image (good with text)", provider="nvidia", path=None, enabled=False,
        licence="Apache-2.0; build.nvidia.com: commercial and non-commercial use",
        blocked_reason="Hosted endpoint not confirmed yet; enable once a live request succeeds."),
    "stable-diffusion-3.5-large": ImageModel(
        key="stable-diffusion-3.5-large", label="Stable Diffusion 3.5 Large", provider="nvidia", path=None, enabled=False,
        licence="build.nvidia.com: ready for non-commercial use; commercial use needs a Stability AI licence",
        blocked_reason="Not licensed for commercial use on the NVIDIA catalog."),
    "flux.1-dev": ImageModel(
        key="flux.1-dev", label="FLUX.1 dev", provider="nvidia", path=None, enabled=False,
        licence="build.nvidia.com: non-commercial use only",
        blocked_reason="Non-commercial licence. Never used in HAIP."),
}


class ImageModelBlocked(Exception):
    pass


class ImageGenError(Exception):
    """A generation failure. `transient` = safe to retry (timeout, 429, 5xx, still queued)."""

    def __init__(self, message: str, *, transient: bool):
        super().__init__(message)
        self.transient = transient


def get_model(key: str) -> ImageModel:
    model = MODELS.get(key)
    if model is None:
        raise ImageModelBlocked(f"Unknown image model: {key}")
    if not model.enabled:
        raise ImageModelBlocked(model.blocked_reason or f"{model.label} is not available.")
    return model


def generate(model: ImageModel, prompt: str, shape: str, seed: Optional[int] = None) -> tuple[bytes, dict]:
    """Return (image bytes, provenance). Raises ImageGenError."""
    if shape not in model.sizes:
        raise ImageGenError(f"{model.label} does not support the {shape!r} shape.", transient=False)
    if model.provider == "nvidia":
        from app.adapters.image.nvidia import generate as nvidia_generate
        return nvidia_generate(model, prompt, *model.sizes[shape], seed=seed)
    raise ImageGenError(f"No adapter for provider {model.provider}", transient=False)
