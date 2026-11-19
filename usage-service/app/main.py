"""
usage-service – main FastAPI application
"""
import logging
import os
import time
import uuid
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import httpx

from .database import AsyncSessionLocal, get_db, init_db
from .models import Model, UsageRecord
from .schemas import (
    ModelOut,
    PaginatedUsage,
    UsageRecordOut,
    UsageRecordRequest,
    UsageRecordResponse,
    UsageSummary,
)
from .seed import seed_models
from .simulator import build_response_preview, call_model

# ── logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | usage-service | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

COST_SERVICE_URL = os.environ.get("COST_SERVICE_URL", "http://cost-service:8000")

# Shared httpx client
_http_client: Optional[httpx.AsyncClient] = None

ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "CORS_ORIGINS",
        "http://localhost:8001,http://127.0.0.1:8001,http://localhost:8002,http://localhost:8003",
    ).split(",")
    if o.strip()
]

# ── app ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="usage-service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Request-ID"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    request_id = request.headers.get("x-request-id", "-")
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "request | request_id=%s method=%s path=%s status=%d duration_ms=%.1f",
        request_id, request.method, request.url.path, response.status_code, duration_ms,
    )
    return response


@app.on_event("startup")
async def startup():
    global _http_client
    _http_client = httpx.AsyncClient(timeout=10.0)
    await init_db()
    async with AsyncSessionLocal() as session:
        await seed_models(session)
    logger.info("usage-service startup complete")


@app.on_event("shutdown")
async def shutdown():
    if _http_client:
        await _http_client.aclose()


def get_http_client() -> httpx.AsyncClient:
    return _http_client


# ── helpers ───────────────────────────────────────────────────────────────────

async def _get_or_create_model(db: AsyncSession, model_name: str) -> Model:
    result = await db.execute(select(Model).where(Model.name == model_name))
    m = result.scalar_one_or_none()
    if m is None:
        m = Model(name=model_name, provider="unknown", is_local=False)
        db.add(m)
        await db.flush()
    return m


# ── /usage/record ─────────────────────────────────────────────────────────────

@app.post("/usage/record", response_model=UsageRecordResponse)
async def record_usage(
    body: UsageRecordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    http_client: httpx.AsyncClient = Depends(get_http_client),
):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4()).replace("-", "")
    logger.info(
        "record | request_id=%s agent_id=%d model=%s source=%s",
        request_id, body.agent_id, body.model, body.source,
    )

    # Simulate / call model
    t0 = time.perf_counter()
    inp, out, latency_ms, status, err_msg = await call_model(
        http_client,
        model=body.model,
        agent_id=body.agent_id,
        prompt=body.prompt or "",
        simulate_failures=body.simulate_failures,
    )
    total = inp + out

    # Ensure model exists in registry
    model_obj = await _get_or_create_model(db, body.model)
    p_preview = (body.prompt or "").strip()[:300] or None
    r_preview = build_response_preview(body.agent_name, body.model, body.prompt or "", inp, out, status)

    usage_row = UsageRecord(
        request_id=request_id,
        agent_id=body.agent_id,
        agent_name=body.agent_name,
        model_id=model_obj.id,
        input_tokens=inp,
        output_tokens=out,
        total_tokens=total,
        latency_ms=latency_ms,
        status=status,
        error_message=err_msg or None,
        source=body.source,
        executed_by=body.executed_by,
        prompt_preview=p_preview,
        response_preview=r_preview,
    )
    db.add(usage_row)
    await db.commit()
    await db.refresh(usage_row)

    logger.info(
        "stored | request_id=%s usage_id=%d status=%s tokens=%d latency_ms=%d",
        request_id, usage_row.id, status, total, latency_ms,
    )

    # Call cost-service
    cost_id = None
    cost_usd = None
    tokens_today = None
    budget_used_pct = None
    alert = None

    try:
        t_cost0 = time.perf_counter()
        cost_resp = await http_client.post(
            f"{COST_SERVICE_URL}/cost/calculate",
            json={
                "usage_id": usage_row.id,
                "request_id": request_id,
                "agent_id": body.agent_id,
                "agent_name": body.agent_name,
                "model": body.model,
                "input_tokens": inp,
                "output_tokens": out,
                "total_tokens": total,
                "daily_token_budget": body.daily_token_budget,
                "source": body.source,
            },
            headers={"x-request-id": request_id},
        )
        cost_ms = int((time.perf_counter() - t_cost0) * 1000)
        logger.info(
            "cost-call | request_id=%s status=%d duration_ms=%d target=cost-service",
            request_id, cost_resp.status_code, cost_ms,
        )
        if cost_resp.status_code == 200:
            cd = cost_resp.json()
            cost_id = cd.get("cost_id")
            cost_usd = str(cd.get("cost_usd", "0"))
            tokens_today = cd.get("tokens_today")
            budget_used_pct = str(cd.get("budget_used_pct", "0"))
            alert = cd.get("alert")
        else:
            logger.warning("cost-service returned %d for request_id=%s", cost_resp.status_code, request_id)
    except Exception as exc:
        logger.error("cost-service call failed: %s (request_id=%s)", exc, request_id)

    return UsageRecordResponse(
        usage_id=usage_row.id,
        request_id=request_id,
        input_tokens=inp,
        output_tokens=out,
        total_tokens=total,
        latency_ms=latency_ms,
        status=status,
        error_message=err_msg or None,
        executed_by=usage_row.executed_by,
        prompt_preview=usage_row.prompt_preview,
        response_preview=usage_row.response_preview,
        cost_id=cost_id,
        cost_usd=cost_usd,
        tokens_today=tokens_today,
        budget_used_pct=budget_used_pct,
        alert=alert,
    )


# ── /usage/live-demo ──────────────────────────────────────────────────────────

@app.post("/usage/live-demo")
async def live_demo(
    body: UsageRecordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    http_client: httpx.AsyncClient = Depends(get_http_client),
):
    """Force Ollama for a single call (optional live demo)."""
    from .simulator import call_model_ollama
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4()).replace("-", "")
    inp, out, latency_ms, status, err_msg = await call_model_ollama(
        http_client, body.model, body.agent_id, body.prompt or "Hello from live demo", False
    )
    total = inp + out
    model_obj = await _get_or_create_model(db, body.model)
    usage_row = UsageRecord(
        request_id=request_id,
        agent_id=body.agent_id,
        agent_name=body.agent_name,
        model_id=model_obj.id,
        input_tokens=inp,
        output_tokens=out,
        total_tokens=total,
        latency_ms=latency_ms,
        status=status,
        error_message=err_msg or None,
        source="demo",
    )
    db.add(usage_row)
    await db.commit()
    await db.refresh(usage_row)
    return {"usage_id": usage_row.id, "status": status, "latency_ms": latency_ms, "total_tokens": total}


# ── /usage (paginated) ────────────────────────────────────────────────────────

def _apply_usage_source_filter(stmt, source: Optional[str]):
    if not source or source == "all":
        return stmt
    if source == "production":
        return stmt.where(UsageRecord.source != "loadtest")
    return stmt.where(UsageRecord.source == source)


def _to_usage_out(row: UsageRecord) -> UsageRecordOut:
    return UsageRecordOut(
        id=row.id,
        request_id=row.request_id,
        agent_id=row.agent_id,
        agent_name=row.agent_name,
        model_id=row.model_id,
        model=row.model_ref.name if row.model_ref else None,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        total_tokens=row.total_tokens,
        latency_ms=row.latency_ms,
        status=row.status,
        error_message=row.error_message,
        source=row.source,
        executed_by=row.executed_by,
        prompt_preview=row.prompt_preview,
        response_preview=row.response_preview,
        created_at=row.created_at,
    )


@app.get("/usage", response_model=PaginatedUsage)
async def list_usage(
    page: int = Query(default=1, ge=1, le=10_000),
    page_size: int = Query(default=20, ge=1, le=200),
    source: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    q = _apply_usage_source_filter(
        select(UsageRecord).options(selectinload(UsageRecord.model_ref)).order_by(UsageRecord.created_at.desc()),
        source,
    )
    count_q = select(func.count()).select_from(_apply_usage_source_filter(select(UsageRecord.id), source).subquery())
    total = (await db.execute(count_q)).scalar_one()
    items = (await db.execute(q.offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return PaginatedUsage(items=[_to_usage_out(r) for r in items], total=total, page=page, page_size=page_size)


@app.get("/usage/agent/{agent_id}", response_model=List[UsageRecordOut])
async def usage_by_agent(
    agent_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UsageRecord)
        .options(selectinload(UsageRecord.model_ref))
        .where(UsageRecord.agent_id == agent_id)
        .order_by(UsageRecord.created_at.desc())
        .limit(limit)
    )
    return [_to_usage_out(r) for r in result.scalars().all()]


@app.get("/usage/model/{model_name}", response_model=List[UsageRecordOut])
async def usage_by_model(
    model_name: str,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    model_obj = await db.execute(select(Model).where(Model.name == model_name))
    m = model_obj.scalar_one_or_none()
    if not m:
        raise HTTPException(404, f"Model '{model_name}' not found")
    result = await db.execute(
        select(UsageRecord)
        .options(selectinload(UsageRecord.model_ref))
        .where(UsageRecord.model_id == m.id)
        .order_by(UsageRecord.created_at.desc())
        .limit(limit)
    )
    return [_to_usage_out(r) for r in result.scalars().all()]


@app.get("/usage/summary", response_model=UsageSummary)
async def usage_summary(source: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    stmt = _apply_usage_source_filter(
        select(
            func.count(UsageRecord.id),
            func.coalesce(func.sum(UsageRecord.input_tokens), 0),
            func.coalesce(func.sum(UsageRecord.output_tokens), 0),
            func.coalesce(func.sum(UsageRecord.total_tokens), 0),
            func.coalesce(func.avg(UsageRecord.latency_ms), 0.0),
            func.count(UsageRecord.id).filter(UsageRecord.status == "success"),
            func.count(UsageRecord.id).filter(UsageRecord.status == "failed"),
        ),
        source,
    )
    row = (await db.execute(stmt)).one()
    return UsageSummary(
        total_requests=row[0],
        input_tokens=row[1],
        output_tokens=row[2],
        total_tokens=row[3],
        avg_latency_ms=float(row[4]),
        success_count=row[5],
        failed_count=row[6],
    )


# ── /models ───────────────────────────────────────────────────────────────────

@app.get("/models", response_model=List[ModelOut])
async def list_models(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Model).order_by(Model.id))
    return result.scalars().all()


# ── /health ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "usage-service"}


@app.get("/health/deps")
async def health_deps(
    db: AsyncSession = Depends(get_db),
    http_client: httpx.AsyncClient = Depends(get_http_client),
):
    # DB check
    try:
        await db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        logger.warning("health/deps db error: %s", e)
        db_status = "error: unavailable"

    # cost-service check
    try:
        r = await http_client.get(f"{COST_SERVICE_URL}/health", timeout=3.0)
        cost_status = "ok" if r.status_code == 200 else f"http {r.status_code}"
    except Exception as e:
        logger.warning("health/deps cost-service error: %s", e)
        cost_status = "error: unavailable"

    return {
        "service": "usage-service",
        "database": db_status,
        "cost-service": cost_status,
    }
