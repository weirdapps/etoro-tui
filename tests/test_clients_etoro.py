# tests/test_clients_etoro.py
import httpx
import pytest
import respx

from etoro_tui.clients.etoro import (
    EtoroAuthError,
    EtoroClient,
    EtoroTransientError,
)

# Sample shape that matches what the live API actually returns.
_PORTFOLIO_OK = {
    "clientPortfolio": {
        "positions": [
            {
                "positionID": 0,
                "openDateTime": "2026-01-01T00:00:00Z",
                "openRate": 215.05,
                "instrumentID": 1005,
                "isBuy": True,
                "amount": 2500.0,
                "units": 10.0,
            }
        ],
        "credit": 0.00,
        "orders": [],
    }
}


@pytest.mark.asyncio
async def test_fetch_portfolio_sets_headers():
    async with respx.mock(base_url="https://public-api.etoro.com") as mock:
        route = mock.get("/api/v1/trading/info/portfolio").respond(200, json=_PORTFOLIO_OK)
        client = EtoroClient(public_key="pk", user_key="uk")
        await client.fetch_portfolio()
        await client.aclose()
        sent = route.calls.last.request
        assert sent.headers["x-api-key"] == "pk"
        assert sent.headers["x-user-key"] == "uk"
        assert "x-request-id" in sent.headers


@pytest.mark.asyncio
async def test_fetch_portfolio_returns_clientPortfolio_inner_dict():
    """Client unwraps the `clientPortfolio` wrapper so callers see {positions, credit, ...}."""
    async with respx.mock(base_url="https://public-api.etoro.com") as mock:
        mock.get("/api/v1/trading/info/portfolio").respond(200, json=_PORTFOLIO_OK)
        client = EtoroClient("pk", "uk")
        data = await client.fetch_portfolio()
        await client.aclose()
        assert data["credit"] == 0.00
        assert len(data["positions"]) == 1
        assert data["positions"][0]["instrumentID"] == 1005


@pytest.mark.asyncio
async def test_401_raises_auth_error_no_retry():
    async with respx.mock(base_url="https://public-api.etoro.com") as mock:
        route = mock.get("/api/v1/trading/info/portfolio").respond(401, json={"error": "Unauthorized"})
        client = EtoroClient("pk", "uk")
        with pytest.raises(EtoroAuthError):
            await client.fetch_portfolio()
        await client.aclose()
        assert route.call_count == 1  # no retry on 401


@pytest.mark.asyncio
async def test_429_retries_then_raises_transient():
    async with respx.mock(base_url="https://public-api.etoro.com") as mock:
        route = mock.get("/api/v1/trading/info/portfolio").respond(429, json={"error": "RateLimited"})
        client = EtoroClient("pk", "uk", max_retries=3, backoff_seconds=(0, 0, 0))
        with pytest.raises(EtoroTransientError):
            await client.fetch_portfolio()
        await client.aclose()
        assert route.call_count == 3


@pytest.mark.asyncio
async def test_429_then_200_succeeds():
    async with respx.mock(base_url="https://public-api.etoro.com") as mock:
        route = mock.get("/api/v1/trading/info/portfolio")
        route.side_effect = [
            httpx.Response(429, json={"error": "RateLimited"}),
            httpx.Response(200, json=_PORTFOLIO_OK),
        ]
        client = EtoroClient("pk", "uk", max_retries=3, backoff_seconds=(0, 0, 0))
        data = await client.fetch_portfolio()
        await client.aclose()
        assert data["credit"] == 0.00
        assert route.call_count == 2


@pytest.mark.asyncio
async def test_no_sleep_after_final_attempt(monkeypatch):
    """Final failed attempt must NOT sleep — saves user wait time when API is down."""
    sleep_calls: list[float] = []

    async def fake_sleep(d: float) -> None:
        sleep_calls.append(d)

    monkeypatch.setattr("asyncio.sleep", fake_sleep)
    async with respx.mock(base_url="https://public-api.etoro.com") as mock:
        mock.get("/api/v1/trading/info/portfolio").respond(429)
        client = EtoroClient("pk", "uk", max_retries=3, backoff_seconds=(1, 2, 3))
        with pytest.raises(EtoroTransientError):
            await client.fetch_portfolio()
        await client.aclose()
    # Should sleep between attempts but NOT after the last failed attempt.
    # 3 attempts → 2 sleeps (after attempts 0 and 1).
    assert sleep_calls == [1, 2]
