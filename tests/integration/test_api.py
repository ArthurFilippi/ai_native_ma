"""API behaviour: demo authentication, deal scoping on every route, the passage endpoint."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from ainma.api import services
from ainma.contracts import (
    VALUE_CONTRACT,
    Answer,
    Deal,
    DocumentMeta,
    KpiValue,
)
from ainma.synth.generate import generate
from tests.integration.conftest import as_user

DEAL_ROUTES: list[tuple[str, str, dict[str, Any] | None]] = [
    ("GET", "/deals/{id}", None),
    ("GET", "/deals/{id}/documents", None),
    ("POST", "/deals/{id}/ask", {"question": "What was the revenue?"}),
    ("POST", "/deals/{id}/screening", {"deal_id": "{id}"}),
    ("GET", "/deals/{id}/kpis", None),
    ("POST", "/deals/{id}/market-intel/run", None),
]


def _fill(
    path: str, body: dict[str, Any] | None, deal_id: str
) -> tuple[str, dict[str, Any] | None]:
    filled = None if body is None else {k: v.replace("{id}", deal_id) for k, v in body.items()}
    return path.replace("{id}", deal_id), filled


async def test_health_needs_no_header(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.parametrize(("method", "path", "body"), DEAL_ROUTES)
async def test_non_member_gets_404_on_every_deal_route(
    client: httpx.AsyncClient, method: str, path: str, body: dict[str, Any] | None
) -> None:
    url, payload = _fill(path, body, "deal_aurora")
    response = await client.request(method, url, json=payload, headers=as_user("u_outsider"))
    assert response.status_code == 404


@pytest.mark.parametrize(("method", "path", "body"), DEAL_ROUTES)
async def test_non_member_gets_404_even_with_an_invalid_body(
    client: httpx.AsyncClient, method: str, path: str, body: dict[str, Any] | None
) -> None:
    url, _ = _fill(path, body, "deal_aurora")
    garbage = {"nonsense": 1} if method == "POST" else None
    response = await client.request(method, url, json=garbage, headers=as_user("u_outsider"))
    assert response.status_code == 404


@pytest.mark.parametrize(("method", "path", "body"), DEAL_ROUTES)
async def test_member_of_another_deal_gets_404(
    client: httpx.AsyncClient, method: str, path: str, body: dict[str, Any] | None
) -> None:
    url, payload = _fill(path, body, "deal_borealis")
    response = await client.request(method, url, json=payload, headers=as_user("u_analyst"))
    assert response.status_code == 404


@pytest.mark.parametrize(("method", "path", "body"), DEAL_ROUTES)
async def test_unknown_deal_gets_404(
    client: httpx.AsyncClient, method: str, path: str, body: dict[str, Any] | None
) -> None:
    url, payload = _fill(path, body, "deal_nowhere")
    response = await client.request(method, url, json=payload, headers=as_user("u_lead"))
    assert response.status_code == 404


@pytest.mark.parametrize(("method", "path", "body"), DEAL_ROUTES)
async def test_missing_header_is_401(
    client: httpx.AsyncClient, method: str, path: str, body: dict[str, Any] | None
) -> None:
    url, payload = _fill(path, body, "deal_aurora")
    response = await client.request(method, url, json=payload)
    assert response.status_code == 401


async def test_unknown_user_is_401(client: httpx.AsyncClient) -> None:
    response = await client.get("/deals", headers=as_user("u_ghost"))
    assert response.status_code == 401


async def test_passage_and_deals_need_a_header(client: httpx.AsyncClient) -> None:
    assert (await client.get("/deals")).status_code == 401
    assert (await client.get("/passages/doc_cim_p2_00")).status_code == 401


async def test_users_are_listed_for_the_demo_switcher(client: httpx.AsyncClient) -> None:
    response = await client.get("/users")
    assert response.status_code == 200
    assert {u["id"] for u in response.json()} == {"u_lead", "u_analyst", "u_outsider"}


async def test_deals_are_filtered_by_access(client: httpx.AsyncClient) -> None:
    async def ids(user: str) -> list[str]:
        response = await client.get("/deals", headers=as_user(user))
        assert response.status_code == 200
        return [Deal.model_validate(d).id for d in response.json()]

    assert await ids("u_analyst") == ["deal_aurora"]
    assert await ids("u_lead") == ["deal_aurora", "deal_borealis"]
    assert await ids("u_outsider") == []


async def test_documents_are_filtered_by_access(client: httpx.AsyncClient) -> None:
    response = await client.get("/deals/deal_aurora/documents", headers=as_user("u_analyst"))
    assert response.status_code == 200
    docs = [
        DocumentMeta.model_validate({k: v for k, v in d.items() if k != "tier"})
        for d in response.json()
    ]
    ids = {d.id for d in docs}
    assert "doc_cim" in ids
    assert "doc_other_cim" not in ids
    assert all(d.deal_id in {"deal_aurora", None} for d in docs)
    assert all("tier" in d for d in response.json())


async def test_passage_is_access_checked(client: httpx.AsyncClient) -> None:
    outsider = await client.get("/passages/doc_cim_p2_00?page=true", headers=as_user("u_outsider"))
    assert outsider.status_code == 404
    other_deal = await client.get("/passages/doc_other_cim_p1_01", headers=as_user("u_analyst"))
    assert other_deal.status_code == 404
    general = await client.get("/passages/doc_playbook_p1_01", headers=as_user("u_outsider"))
    assert general.status_code == 200


async def test_passage_returns_page_text_and_offsets(client: httpx.AsyncClient) -> None:
    response = await client.get("/passages/doc_cim_p2_01?page=true", headers=as_user("u_analyst"))
    assert response.status_code == 200
    body = response.json()
    assert body["chunk"]["id"] == "doc_cim_p2_01"
    assert body["document"]["id"] == "doc_cim"
    assert body["document"]["tier"] == 2
    start, end = body["highlight_start"], body["highlight_end"]
    assert body["page_text"][start:end] == body["chunk"]["text"]


async def test_passage_without_page_flag_omits_page_text(client: httpx.AsyncClient) -> None:
    response = await client.get("/passages/doc_cim_p2_01", headers=as_user("u_analyst"))
    assert response.status_code == 200
    assert response.json()["page_text"] is None


async def test_unknown_passage_is_404(client: httpx.AsyncClient) -> None:
    response = await client.get("/passages/nope?page=true", headers=as_user("u_lead"))
    assert response.status_code == 404


async def test_every_ask_response_carries_the_value_contract(client: httpx.AsyncClient) -> None:
    for question in ("What was FY2024 revenue?", "What is the CEO compensation?"):
        response = await client.post(
            "/deals/deal_aurora/ask", json={"question": question}, headers=as_user("u_analyst")
        )
        assert response.status_code == 200
        answer = Answer.model_validate(response.json())
        assert answer.value_contract == VALUE_CONTRACT
        assert answer.user_id == "u_analyst"
        assert answer.deal_id == "deal_aurora"
        assert answer.question == question


async def test_ask_runs_the_real_pipeline_on_the_visible_deal(client: httpx.AsyncClient) -> None:
    revenue = await client.post(
        "/deals/deal_aurora/ask",
        json={"question": "What was FY2024 revenue?"},
        headers=as_user("u_analyst"),
    )
    assert revenue.status_code == 200
    answer = Answer.model_validate(revenue.json())
    assert answer.user_id == "u_analyst" and answer.deal_id == "deal_aurora"
    assert answer.contradictions
    absent = await client.post(
        "/deals/deal_aurora/ask",
        json={"question": "What is the CEO compensation package?"},
        headers=as_user("u_analyst"),
    )
    assert absent.json()["abstained"] is True


async def test_empty_question_is_rejected(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/deals/deal_aurora/ask", json={"question": ""}, headers=as_user("u_analyst")
    )
    assert response.status_code == 422


async def test_kpis_and_market_intel_run_on_the_tiny_store(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    # Only the ground truth of seed 1234 is committed: generate the news feed into a tmp folder.
    root = tmp_path_factory.mktemp("synthetic")
    generate(1234, root)
    monkeypatch.setattr(services, "SYNTHETIC_ROOT", root)
    headers = as_user("u_analyst")
    kpis = await client.get("/deals/deal_aurora/kpis", headers=headers)
    assert kpis.status_code == 200
    assert [KpiValue.model_validate(k) for k in kpis.json()]
    market = await client.post("/deals/deal_aurora/market-intel/run", headers=headers)
    assert market.status_code == 200
    assert market.json()["deal_id"] == "deal_aurora"


async def test_screening_body_cannot_name_another_deal(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/deals/deal_aurora/screening",
        json={"deal_id": "deal_borealis"},
        headers=as_user("u_lead"),
    )
    assert response.status_code == 422


async def test_openapi_schema_and_examples(app: FastAPI) -> None:
    schema = app.openapi()
    assert "/passages/{chunk_id}" in schema["paths"]
    assert "DEMO_AUTH" in schema["info"]["description"]
    ask = schema["paths"]["/deals/{deal_id}/ask"]["post"]["responses"]["200"]["content"]
    examples = ask["application/json"]["examples"]
    assert {"contradiction", "abstention"} <= set(examples)
    assert schema["components"]["securitySchemes"]


async def test_cors_allows_the_configured_origin(client: httpx.AsyncClient) -> None:
    response = await client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
