# src/etoro_tui/clients/etoro.py
"""Async eToro REST client with retry+backoff.

Hits `https://public-api.etoro.com/api/v1/trading/info/portfolio` — the only
real-data endpoint we found that works for retail accounts. Returns the raw
`clientPortfolio` dict (positions list + credit). Conversion to dataclasses
happens in app.py so this module stays free of model dependencies.

There is intentionally no `fetch_account` method — eToro's portfolio response
already contains `credit` (cash). Equity is computed locally from positions
+ credit. See docs/etoro-api-actual.md for the full API discovery.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

import httpx

from ..config import ETORO_BASE_URL

log = logging.getLogger(__name__)

DEFAULT_BACKOFF = (5, 15, 60)


class EtoroAuthError(RuntimeError):
    """401 from eToro — credentials invalid. No retry."""


class EtoroTransientError(RuntimeError):
    """Retries exhausted (429 / 5xx / network)."""


class EtoroClient:
    def __init__(
        self,
        public_key: str,
        user_key: str,
        base_url: str = ETORO_BASE_URL,
        max_retries: int = 3,
        backoff_seconds: tuple[int, ...] = DEFAULT_BACKOFF,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._pk = public_key
        self._uk = user_key
        self._max_retries = max_retries
        self._backoff = backoff_seconds
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout_seconds,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._pk,
            "x-user-key": self._uk,
            "x-request-id": str(uuid.uuid4()),
            "Content-Type": "application/json",
        }

    async def _get(self, path: str) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                resp = await self._client.get(path, headers=self._headers())
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_error = e
                if attempt < self._max_retries - 1:
                    await self._sleep(attempt)
                continue
            if resp.status_code == 401:
                raise EtoroAuthError(f"401 Unauthorized on {path}")
            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                last_error = httpx.HTTPStatusError(
                    f"{resp.status_code}", request=resp.request, response=resp
                )
                if attempt < self._max_retries - 1:
                    await self._sleep(attempt)
                continue
            resp.raise_for_status()
            return resp.json()
        raise EtoroTransientError(f"{path}: exhausted {self._max_retries} retries: {last_error}")

    async def _sleep(self, attempt: int) -> None:
        delay = self._backoff[min(attempt, len(self._backoff) - 1)]
        if delay > 0:
            await asyncio.sleep(delay)

    async def fetch_portfolio(self) -> dict[str, Any]:
        """Return the `clientPortfolio` dict.

        Shape: {positions: [...], credit: float, orders: [...], ...}.
        Caller is responsible for resolving instrumentID→symbol and computing
        per-position pnl/value (eToro doesn't return those).
        """
        raw = await self._get("/api/v1/trading/info/portfolio")
        return raw.get("clientPortfolio", {})

    async def fetch_rates(
        self,
        instrument_ids: list[int],
        batch_size: int = 50,
    ) -> dict[int, dict[str, Any]]:
        """Live last/bid/ask + current FX for each instrument.

        Endpoint: GET /api/v1/market-data/instruments/rates?instrumentIds=…

        Returns {instrumentID: rate_dict} where rate_dict has at minimum:
            lastExecution, ask, bid               — all in instrument's local currency
            conversionRateAsk, conversionRateBid  — local→USD multiplier
            date                                   — ISO 8601 UTC

        eToro is inconsistent about the key name: this endpoint returns
        `instrumentID` (capital ID), same as the portfolio endpoint, but
        census uses `instrumentId`. Be careful when joining datasets.

        Batches at 50 IDs/request to stay under URL-length limits. Each batch
        is a separate retry-protected HTTP call; partial failures (one batch
        returns transient error) propagate as EtoroTransientError after
        retries — the caller should fall back to census prices in that case.
        """
        if not instrument_ids:
            return {}
        out: dict[int, dict[str, Any]] = {}
        for i in range(0, len(instrument_ids), batch_size):
            batch = instrument_ids[i : i + batch_size]
            path = (
                "/api/v1/market-data/instruments/rates"
                f"?instrumentIds={','.join(str(x) for x in batch)}"
            )
            resp = await self._get(path)
            for r in resp.get("rates", []):
                # Defensive: tolerate either casing in case eToro normalises later.
                key = r.get("instrumentID", r.get("instrumentId"))
                if key is not None:
                    out[int(key)] = r
        return out
