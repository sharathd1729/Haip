"""Text embedding adapter — NVIDIA NIM retrieval models.

Before this module the codebase had pgvector, an `embeddings` table and a
cosine-search function, but no way to actually turn text into a vector. This
fills that gap.

Routing note: CLAUDE.md mandates all model access go through the adapter
layer, never a provider client imported into a service. Embeddings are not
part of `_TASK_ROUTES` (that dict maps chat tasks to chat models), so this
module is the embedding equivalent of `get_llm()` -- callers ask for
`embed_texts()` and never touch the provider.

Model: nvidia/nv-embedqa-e5-v5 (1024 dims). This is an *asymmetric*
retrieval model: stored passages and search queries must be embedded with
different `input_type` values or recall degrades badly. Callers must say
which they are producing -- there is deliberately no default.
"""

from __future__ import annotations

import asyncio
from typing import Literal, Sequence

import structlog

from app.core.config import settings

log = structlog.get_logger()

_BASE_URL = "https://integrate.api.nvidia.com/v1"

EMBED_MODEL = "nvidia/nv-embedqa-e5-v5"
EMBED_DIM = 1024

# NVIDIA's embedding endpoint rejects oversized batches; keep well under it.
_MAX_BATCH = 32
# Model context is 512 tokens. Chunking upstream should keep inputs far below
# this, but a hard character cap stops a pathological entry from erroring the
# whole batch (roughly 4 chars/token, with headroom).
_MAX_CHARS = 1800

InputType = Literal["passage", "query"]


class EmbeddingError(RuntimeError):
    """Raised when embeddings could not be produced. Callers are expected to
    mark their rows failed rather than silently storing a zero vector -- a
    zero vector is not 'no result', it is a vector that matches everything
    equally and quietly poisons retrieval."""


def _api_key() -> str:
    # Reuse the FAST group: embedding calls are high-volume and short, the
    # same rate-limit profile as the 8B classify traffic that key serves.
    return settings.NVIDIA_API_KEY_FAST or settings.NVIDIA_API_KEY


async def embed_texts(texts: Sequence[str], input_type: InputType) -> list[list[float]]:
    """Embed a batch of texts. Returns one vector per input, order preserved.

    `input_type` must be "passage" when indexing stored content and "query"
    when embedding a user's search string.
    """
    if not texts:
        return []

    api_key = _api_key()
    if not api_key:
        raise EmbeddingError(
            "No NVIDIA API key set. Set NVIDIA_API_KEY (or NVIDIA_API_KEY_FAST) in .env. "
            "Get keys at https://build.nvidia.com"
        )

    try:
        import openai
    except ImportError:  # pragma: no cover - dependency is declared
        raise EmbeddingError("openai package not installed. Run: pip install openai")

    client = openai.AsyncOpenAI(api_key=api_key, base_url=_BASE_URL)
    cleaned = [(t or "").strip()[:_MAX_CHARS] or " " for t in texts]

    out: list[list[float]] = []
    for start in range(0, len(cleaned), _MAX_BATCH):
        batch = cleaned[start:start + _MAX_BATCH]
        try:
            resp = await client.embeddings.create(
                model=EMBED_MODEL,
                input=batch,
                extra_body={"input_type": input_type, "truncate": "END"},
            )
        except Exception as exc:
            log.error("embed_batch_failed", error=str(exc), batch_size=len(batch), input_type=input_type)
            raise EmbeddingError(f"Embedding request failed: {exc}") from exc

        # The API documents order preservation, but a silent reorder would
        # attach every vector to the wrong entry -- a corruption that is
        # invisible until retrieval quality is mysteriously bad. Sort by the
        # returned index rather than trusting position.
        for item in sorted(resp.data, key=lambda d: d.index):
            vec = list(item.embedding)
            if len(vec) != EMBED_DIM:
                raise EmbeddingError(
                    f"Expected {EMBED_DIM}-dim vectors from {EMBED_MODEL}, got {len(vec)}. "
                    "The embeddings column and migration 078 assume 1024."
                )
            out.append(vec)

    return out


async def embed_one(text: str, input_type: InputType) -> list[float]:
    vecs = await embed_texts([text], input_type)
    if not vecs:
        raise EmbeddingError("Embedding returned no vectors")
    return vecs[0]


def embed_texts_sync(texts: Sequence[str], input_type: InputType) -> list[list[float]]:
    """Blocking wrapper for Celery tasks, which are sync functions."""
    return asyncio.run(embed_texts(texts, input_type))


def embed_one_sync(text: str, input_type: InputType) -> list[float]:
    return asyncio.run(embed_one(text, input_type))
