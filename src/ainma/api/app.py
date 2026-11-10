"""FastAPI application factory.

DEMO_AUTH: callers identify themselves with the `X-User-Id` header. This is demo authentication
and not production authentication: anybody can claim any registered user. Real authentication is
deferred. What it does guarantee is the access model: every route resolves an `AccessContext`
and the store filters on it, so a user without membership gets 404 for a deal and all of its
content.
"""

# No `from __future__ import annotations`: FastAPI resolves the dependency aliases below at
# definition time, and they are local to `build_router`.

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader

from ainma.api import services
from ainma.api.examples_openapi import ANSWER_EXAMPLES, SCREENING_EXAMPLES
from ainma.api.schemas import AskRequest, HealthResponse, MarketIntelRun, PassageResponse
from ainma.contracts import (
    AccessContext,
    Answer,
    Deal,
    DocumentMeta,
    KpiValue,
    MarketEvent,
    Role,
    ScreeningRequest,
    ScreeningResult,
    User,
)
from ainma.llm import LLMError
from ainma.runtime import Runtime
from ainma.store import UnknownUserError

logger = logging.getLogger(__name__)

log = logging.getLogger(__name__)

USER_HEADER = "X-User-Id"

DESCRIPTION = (
    "Deal-centric API for sourced answers, buyer screening and KPI extraction.\n\n"
    "**DEMO_AUTH, not production authentication.** Callers send `X-User-Id` with a registered "
    "user id. A missing header or an unknown user gives 401. A user without membership of a "
    "deal gets 404, not 403, for the deal and for every passage, document and result of it."
)

_user_header = APIKeyHeader(
    name=USER_HEADER,
    auto_error=False,
    description="DEMO_AUTH: a registered user id such as u_analyst. Not production authentication.",
)


def _examples(payloads: dict[str, dict[str, Any]]) -> dict[int | str, dict[str, Any]]:
    content = {
        "application/json": {
            "examples": {
                name: {"summary": name, "value": value} for name, value in payloads.items()
            }
        }
    }
    return {200: {"description": "Successful response", "content": content}}


def build_router(runtime: Runtime) -> APIRouter:
    router = APIRouter()
    store = runtime.store

    async def access_context(
        user_id: Annotated[str | None, Security(_user_header)] = None,
    ) -> AccessContext:
        if not runtime.settings.demo_auth:
            raise HTTPException(401, "authentication is not configured")
        if not user_id:
            raise HTTPException(401, f"missing {USER_HEADER} header (DEMO_AUTH)")
        try:
            return await store.access_for(user_id)
        except UnknownUserError:
            raise HTTPException(401, "unknown user") from None

    Access = Annotated[AccessContext, Depends(access_context)]  # noqa: N806

    async def deal_scope(deal_id: str, access: Access) -> Deal:
        """Resolve the deal for the caller. Not a member, or no such deal: 404."""
        deal = await store.get_deal(deal_id, access)
        if deal is None:
            raise HTTPException(404, "deal not found")
        return deal

    DealOf = Annotated[Deal, Depends(deal_scope)]  # noqa: N806

    async def writer_scope(deal: DealOf, access: Access) -> Deal:
        """A `viewer` reads answers and documents only: no screening, no ingestion (403)."""
        if await store.role_in(deal.id, access.user_id) is Role.VIEWER:
            raise HTTPException(403, "a viewer cannot run this action")
        return deal

    WriterOf = Annotated[Deal, Depends(writer_scope)]  # noqa: N806

    @router.get("/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            auth="DEMO_AUTH" if runtime.settings.demo_auth else "disabled",
            llm_provider=runtime.llm.provider,
            store_backend=runtime.settings.store_backend,
        )

    @router.get("/users", response_model=list[User], tags=["demo"])
    async def users() -> list[User]:
        """Registered demo users, for the user switcher. DEMO_AUTH only."""
        return await store.list_users()

    @router.get("/deals", response_model=list[Deal], tags=["deals"])
    async def deals(access: Access) -> list[Deal]:
        return await store.list_deals(access)

    @router.get("/deals/{deal_id}", response_model=Deal, tags=["deals"])
    async def deal(deal: DealOf) -> Deal:
        return deal

    @router.get("/deals/{deal_id}/documents", response_model=list[DocumentMeta], tags=["deals"])
    async def documents(deal: DealOf, access: Access) -> list[DocumentMeta]:
        return await store.list_documents(access, deal.id)

    @router.post(
        "/deals/{deal_id}/ask",
        response_model=Answer,
        responses=_examples(ANSWER_EXAMPLES),
        tags=["answers"],
    )
    async def ask(body: AskRequest, deal: DealOf, access: Access) -> Answer:
        return await services.ask(runtime, access, deal.id, body.question)

    @router.get("/passages/{chunk_id}", response_model=PassageResponse, tags=["answers"])
    async def passage(
        chunk_id: str, access: Access, page: Annotated[bool, Query()] = False
    ) -> PassageResponse:
        """A cited chunk with its document, optionally with the page text.

        The access predicate runs inside the store query: a chunk the caller cannot see is 404.
        """
        chunk = await store.get_chunk(chunk_id, access)
        document = (
            await store.get_document(chunk.document_id, access) if chunk is not None else None
        )
        if chunk is None or document is None:
            raise HTTPException(404, "passage not found")
        page_text = await store.get_page(chunk.document_id, chunk.page, access) if page else None
        return PassageResponse(
            chunk=chunk,
            document=document,
            page_text=page_text,
            highlight_start=chunk.char_start,
            highlight_end=chunk.char_end,
        )

    @router.post(
        "/deals/{deal_id}/screening",
        response_model=ScreeningResult,
        responses=_examples(SCREENING_EXAMPLES),
        tags=["screening"],
    )
    async def screening(body: ScreeningRequest, deal: WriterOf, access: Access) -> ScreeningResult:
        if body.deal_id != deal.id:
            raise HTTPException(422, "deal_id in the body does not match the path")
        return await services.screening(runtime, access, body)

    @router.get("/deals/{deal_id}/kpis", response_model=list[KpiValue], tags=["kpis"])
    async def kpis(deal: DealOf, access: Access) -> list[KpiValue]:
        return await services.kpis(runtime, access, deal.id)

    @router.get("/deals/{deal_id}/events", response_model=list[MarketEvent], tags=["market"])
    async def events(deal: DealOf, access: Access) -> list[MarketEvent]:
        """Market events read from the deal's news: duplicates merged, denials and corrections
        applied, every report cited verbatim. A denied rumour is never a fact."""
        return await services.events(runtime, access, deal.id)

    @router.post(
        "/deals/{deal_id}/market-intel/run", response_model=MarketIntelRun, tags=["market"]
    )
    async def market_intel(deal: WriterOf, access: Access) -> MarketIntelRun:
        """Run the simulated market intelligence connector and ingest its items into the deal."""
        ingested = await services.market_intel(runtime, access, deal.id)
        return MarketIntelRun(deal_id=deal.id, ingested=ingested)

    return router


def create_app(runtime: Runtime) -> FastAPI:
    app = FastAPI(title="AI-native M&A", version="0.1.0", description=DESCRIPTION)
    origins = [o.strip() for o in runtime.settings.allowed_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    app.include_router(build_router(runtime))

    @app.exception_handler(LLMError)
    async def llm_failed(request: Request, error: LLMError) -> JSONResponse:
        # no silent mock answer: the client is told the model failed (D88)
        logger.warning("LLM failure on %s: %s", request.url.path, error)
        return JSONResponse(
            status_code=503,
            content={
                "detail": f"The language model failed ({error}); no answer was produced. "
                "Retry later or check the provider configuration."
            },
        )

    return app
