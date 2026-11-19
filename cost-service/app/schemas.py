"""
cost-service – Pydantic schemas
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Pricing ──────────────────────────────────────────────────────────────────

class PricingBase(BaseModel):
    model: str = Field(..., min_length=1, max_length=100)
    input_price_per_1k: Decimal = Field(..., ge=0)
    output_price_per_1k: Decimal = Field(..., ge=0)
    currency: str = Field(default="USD", min_length=1, max_length=10)


class PricingCreate(PricingBase):
    pass


class PricingUpdate(BaseModel):
    input_price_per_1k: Optional[Decimal] = Field(default=None, ge=0)
    output_price_per_1k: Optional[Decimal] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, min_length=1, max_length=10)


class PricingOut(PricingBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    updated_at: Optional[datetime] = None


# ── Cost calculation ──────────────────────────────────────────────────────────

class CostCalculateRequest(BaseModel):
    usage_id: int = Field(..., ge=1)
    request_id: str = Field(..., min_length=1, max_length=64)
    agent_id: int = Field(..., ge=1)
    agent_name: str = Field(..., min_length=1, max_length=120)
    model: str = Field(..., min_length=1, max_length=100)
    input_tokens: int = Field(..., ge=0)
    output_tokens: int = Field(..., ge=0)
    total_tokens: int = Field(..., ge=0)
    daily_token_budget: int = Field(..., ge=0, le=100_000_000)
    source: str = Field(default="demo", min_length=1, max_length=40)


class CostCalculateResponse(BaseModel):
    cost_id: int
    cost_usd: Decimal
    tokens_today: int
    budget_used_pct: Decimal
    alert: Optional[str] = None          # "WARNING" | "CRITICAL" | None


# ── Cost record out ───────────────────────────────────────────────────────────

class CostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    usage_id: int
    request_id: str
    agent_id: int
    agent_name: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: Decimal
    source: str
    created_at: datetime


# ── Alerts ───────────────────────────────────────────────────────────────────

class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    agent_id: int
    agent_name: str
    level: str
    budget_used_pct: Decimal
    tokens_today: int
    daily_token_budget: int
    alert_date: date
    message: str
    created_at: datetime


# ── Analytics ─────────────────────────────────────────────────────────────────

class OverviewAnalytics(BaseModel):
    total_requests: int
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int
    total_cost_usd: Decimal
    failed_model_calls: int


class ModelAnalytics(BaseModel):
    model: str
    request_count: int
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int
    total_cost_usd: Decimal


class AgentAnalytics(BaseModel):
    agent_id: int
    agent_name: str
    request_count: int
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int
    total_cost_usd: Decimal
    tokens_today: int
    budget_used_pct: Optional[Decimal] = None
