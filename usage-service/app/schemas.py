"""
usage-service – Pydantic schemas
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class UsageRecordRequest(BaseModel):
    agent_id: int = Field(..., ge=1)
    agent_name: str = Field(..., min_length=1, max_length=120)
    model: str = Field(..., min_length=1, max_length=100)
    daily_token_budget: int = Field(..., ge=0, le=100_000_000)
    prompt: Optional[str] = Field(default="", max_length=16_000)
    source: str = Field(default="demo", min_length=1, max_length=40)
    simulate_failures: bool = False
    executed_by: Optional[str] = Field(default=None, max_length=120)


class UsageRecordResponse(BaseModel):
    usage_id: int
    request_id: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: int
    status: str                         # success | failed
    error_message: Optional[str] = None
    executed_by: Optional[str] = None
    prompt_preview: Optional[str] = None
    response_preview: Optional[str] = None
    # cost chain result
    cost_id: Optional[int] = None
    cost_usd: Optional[str] = None
    tokens_today: Optional[int] = None
    budget_used_pct: Optional[str] = None
    alert: Optional[str] = None


class UsageRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    request_id: str
    agent_id: int
    agent_name: str
    model_id: int
    model: Optional[str] = None
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: int
    status: str
    error_message: Optional[str] = None
    source: str
    executed_by: Optional[str] = None
    prompt_preview: Optional[str] = None
    response_preview: Optional[str] = None
    created_at: datetime


class ModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    provider: str
    is_local: bool


class UsageSummary(BaseModel):
    total_requests: int
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int
    avg_latency_ms: float
    success_count: int
    failed_count: int


class PaginatedUsage(BaseModel):
    items: List[UsageRecordOut]
    total: int
    page: int
    page_size: int
