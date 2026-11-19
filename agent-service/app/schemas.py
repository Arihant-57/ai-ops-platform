"""
agent-service – Pydantic schemas
"""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Agent ─────────────────────────────────────────────────────────────────────

class AgentBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=500)
    owner_team: str = Field(default="default", min_length=1, max_length=100)
    model: str = Field(..., min_length=1, max_length=100)
    daily_token_budget: int = Field(default=100_000, ge=0, le=100_000_000)
    budget_mode: Literal["soft", "hard"] = "soft"
    status: Literal["ACTIVE", "INACTIVE"] = "ACTIVE"


class AgentCreate(AgentBase):
    pass


class AgentUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=500)
    owner_team: Optional[str] = Field(default=None, min_length=1, max_length=100)
    model: Optional[str] = Field(default=None, min_length=1, max_length=100)
    daily_token_budget: Optional[int] = Field(default=None, ge=0, le=100_000_000)
    budget_mode: Optional[Literal["soft", "hard"]] = None
    status: Optional[Literal["ACTIVE", "INACTIVE"]] = None


class AgentOut(AgentBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime


# ── Run request / response ────────────────────────────────────────────────────

class RunRequest(BaseModel):
    prompt: Optional[str] = Field(default="", max_length=16_000)
    source: str = Field(default="demo", min_length=1, max_length=40)
    simulate_failures: bool = False
    executed_by: Optional[str] = Field(default=None, max_length=120)


# ── Teams & Members ───────────────────────────────────────────────────────────

class TeamMemberCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    email: Optional[str] = Field(default=None, max_length=254)
    role: Literal["admin", "developer", "viewer"] = "developer"


class TeamMemberOut(TeamMemberCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    team_id: int
    created_at: datetime


class TeamCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    daily_token_budget: int = Field(default=500_000, ge=0, le=100_000_000)


class TeamUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    daily_token_budget: Optional[int] = Field(default=None, ge=0, le=100_000_000)


class TeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: Optional[str] = None
    daily_token_budget: int
    created_at: datetime
    members: List[TeamMemberOut] = []
    member_count: int = 0
    agent_count: int = 0


class UsageInfo(BaseModel):
    usage_id: Optional[int] = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    status: str = "success"
    error_message: Optional[str] = None
    executed_by: Optional[str] = None
    prompt_preview: Optional[str] = None
    response_preview: Optional[str] = None


class CostInfo(BaseModel):
    cost_id: Optional[int] = None
    cost_usd: Optional[str] = None
    tokens_today: Optional[int] = None
    budget_used_pct: Optional[str] = None
    alert: Optional[str] = None


class RunResponse(BaseModel):
    request_id: str
    trace: List[str]
    agent: AgentOut
    usage: UsageInfo
    cost: CostInfo
    timings_ms: Dict[str, float]


# ── Dashboard ─────────────────────────────────────────────────────────────────

class DashboardOverview(BaseModel):
    agents: List[AgentOut]
    total_requests: int
    total_tokens: int
    total_cost_usd: str
    failed_model_calls: int
    cost_per_model: List[Dict[str, Any]]
    tokens_per_agent: List[Dict[str, Any]]
    recent_alerts: List[Dict[str, Any]]
