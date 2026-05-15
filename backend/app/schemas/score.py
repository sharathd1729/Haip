from pydantic import BaseModel
from typing import Optional, List, Any


class EvidenceSpan(BaseModel):
    t0: float
    t1: float
    quote: str


class CriterionScore(BaseModel):
    id: str
    score: float
    evidence: List[EvidenceSpan] = []
    confidence: Optional[float] = None


class CallScoreOut(BaseModel):
    id: str
    call_id: str
    rubric_id: str
    total_score: float
    max_score: float
    percentage: float
    has_auto_fail: bool = False
    criterion_scores: List[Any] = []
    model_used: str
    ai_confidence: Optional[float] = None
    is_overridden: bool = False
    override_reason: Optional[str] = None

    class Config:
        from_attributes = True


class ScoreOverrideRequest(BaseModel):
    criterion_scores: List[Any]
    reason: str
