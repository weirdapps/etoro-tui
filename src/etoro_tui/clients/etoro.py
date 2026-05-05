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
        raise EtoroTransientError(
            f"{path}: exhausted {self._max_retries} retries: {last_error}"
        )

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
