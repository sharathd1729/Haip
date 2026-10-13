from datetime import datetime
from typing import Optional, Literal, List
from pydantic import BaseModel, Field, model_validator


# Categories a tenant files knowledge under. Kept deliberately close to what
# a hospitality owner actually thinks in ("what are my add-ons?") rather than
# an abstract taxonomy -- these are surfaced verbatim as filter tabs in the UI.
KnowledgeCategory = Literal[
    "pricing", "availability", "amenities", "addons",
    "location", "routes", "faq", "policy", "other",
]

KnowledgeSource = Literal["manual", "website", "document", "conversation"]

# Anything not authored by a human on the tenant's team lands in `pending`
# and is invisible to the concierge until someone approves it. Scraped and
# conversation-mined content is a suggestion, never truth.
ReviewStatus = Literal["approved", "pending", "rejected"]

EmbeddingStatus = Literal["pending", "done", "failed"]


class KnowledgeEntryCreate(BaseModel):
    category: KnowledgeCategory = "faq"
    question: Optional[str] = Field(default=None, max_length=500)
    content: str = Field(min_length=1, max_length=8000)
    property_id: Optional[str] = None
    source_url: Optional[str] = Field(default=None, max_length=2000)
    # Manual entries outrank scraped/mined ones at equal similarity; see
    # knowledge_service.search()'s ordering.
    priority: int = Field(default=0, ge=0, le=100)

    @model_validator(mode="after")
    def _faq_needs_question(self):
        if self.category == "faq" and not (self.question or "").strip():
            raise ValueError("question is required for faq entries")
        return self


class KnowledgeEntryUpdate(BaseModel):
    category: Optional[KnowledgeCategory] = None
    question: Optional[str] = Field(default=None, max_length=500)
    content: Optional[str] = Field(default=None, min_length=1, max_length=8000)
    property_id: Optional[str] = None
    priority: Optional[int] = Field(default=None, ge=0, le=100)
    is_active: Optional[bool] = None
    review_status: Optional[ReviewStatus] = None
    # Generated automatically; editable so a tenant can delete one that
    # misses the point. Sending [] clears them without triggering regeneration.
    alt_phrasings: Optional[List[str]] = Field(default=None, max_length=20)
    # True = "keep this passage even though the page/file it came from no longer contains it".
    keep_out_of_date: Optional[bool] = None


class KnowledgeEntryOut(BaseModel):
    id: str
    tenant_id: str
    category: str
    question: Optional[str] = None
    content: str
    property_id: Optional[str] = None
    source: str
    source_url: Optional[str] = None
    source_ref: Optional[str] = None
    file_s3_key: Optional[str] = None
    alt_phrasings: Optional[List[str]] = None
    priority: int
    is_active: bool
    review_status: str
    embedding_status: str
    embedding_error: Optional[str] = None
    embedding_attempts: int = 0
    embedded_at: Optional[datetime] = None
    stale_since: Optional[datetime] = None
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class KnowledgeEntryList(BaseModel):
    items: List[KnowledgeEntryOut]
    total: int


class KnowledgeSearchHit(BaseModel):
    """One retrieval result. `score` is cosine similarity in [0,1]."""
    id: str
    category: str
    question: Optional[str] = None
    content: str
    source: str
    property_id: Optional[str] = None
    score: float


class KnowledgeSearchRequest(BaseModel):
    """`conversation_id`, when given, makes the test use that conversation's property -- exactly what a real reply would use."""
    query: str = Field(min_length=1, max_length=1000)
    property_id: Optional[str] = None
    conversation_id: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=20)


class KnowledgeSearchResponse(BaseModel):
    query: str
    hits: List[KnowledgeSearchHit]
    # ok | no_match | embedding_unavailable | search_failed | unsupported -- a failed lookup is not "no answer".
    status: str = "ok"
    message: str = ""
    property_id: Optional[str] = None
    retrievable_count: int = 0


class WebsiteIngestRequest(BaseModel):
    url: str = Field(max_length=2000)
    # Bounded so one call can't crawl an entire site into the embedding bill.
    max_pages: int = Field(default=10, ge=1, le=50)
    same_domain_only: bool = True


class IngestJobResponse(BaseModel):
    job_id: str
    status: str
    message: str


class KnowledgeCrawlRequest(BaseModel):
    """Explicit list of page URLs to ingest -- not a recursive crawler
    (no link-following). A tenant pastes the specific pages that actually
    matter (FAQ, amenities, policies) rather than the AI wandering their
    whole site; keeps this bounded, fast, and predictable.

    max_length must match knowledge_ingest.MAX_URLS_PER_REQUEST -- this is
    the actual enforcement point (a 422 before the endpoint body ever
    runs); keep the two in sync if either changes."""
    urls: List[str] = Field(min_length=1, max_length=5)


class KnowledgeIngestResult(BaseModel):
    entries_created: int
    message: str
    unchanged: int = 0
    marked_out_of_date: int = 0
