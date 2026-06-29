# src/etoro_tui/clients/price_stream.py
"""Real-time eToro price stream over WebSocket.

Replaces REST price polling with a push feed. Maintains an in-memory rates
store normalized to the REST `fetch_rates()` shape so the existing app pipeline
consumes it unchanged. See docs/etoro-websocket-actual.md for the verified
protocol.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

from websockets.asyncio.client import connect

log = logging.getLogger(__name__)

WS_URL = "wss://ws.etoro.com/ws"

# Auth errors that mean "stop trying" rather than "back off and retry".
_FATAL_AUTH_CODES = {"Unauthorized", "InvalidKey", "Forbidden"}

# WS PascalCase -> REST camelCase. Price fields update every delta; FX fields
# arrive only in the snapshot and must persist across price-only deltas.
_PRICE_FIELDS = {"LastExecution": "lastExecution", "Ask": "ask", "Bid": "bid"}
_FX_FIELDS = {"ConversionRateAsk": "conversionRateAsk", "ConversionRateBid": "conversionRateBid"}


def ws_content_to_rate(content: dict, prev: dict | None) -> dict:
    """Merge a parsed WS instrument-content dict onto the previous rate dict.

    Returns a REST-shaped dict ({lastExecution, ask, bid, conversionRateAsk,
    conversionRateBid, date}). Numeric fields become floats; unparseable values
    are skipped. Price/FX from `prev` persist when this frame omits them — so a
    price-only delta keeps the snapshot's conversion rate, and a price-less
    frame keeps the last price.
    """
    out = dict(prev) if prev else {}
    for ws_key, rest_key in (*_PRICE_FIELDS.items(), *_FX_FIELDS.items()):
        if ws_key in content:
            try:
                out[rest_key] = float(content[ws_key])
            except (TypeError, ValueError):
                continue
    if "Date" in content:
        out["date"] = content["Date"]
    return out


def _envelope(operation: str, data: dict) -> str:
    return json.dumps({"id": str(uuid.uuid4()), "operation": operation, "data": data})


def _topics(ids: set[int]) -> list[str]:
    return [f"instrument:{i}" for i in sorted(ids)]


class EtoroPriceStream:
    """One authenticated WS connection + an in-memory REST-shaped rates store.

    Background task connects, authenticates (apiKey=public_key,
    userKey=user_key), subscribes to instrument topics, and updates the store on
    every tick. Auto-reconnects with backoff; re-subscribes on reconnect.
    All failures are contained here — callers see a stale store + is_connected()
    False, never an exception.
    """

    def __init__(
        self,
        public_key: str,
        user_key: str,
        *,
        url: str = WS_URL,
        backoff_seconds: tuple[int, ...] = (5, 15, 60),
        ping_interval: float = 20.0,
    ) -> None:
        self._pk = public_key
        self._uk = user_key
        self._url = url
        self._backoff = backoff_seconds
        self._ping_interval = ping_interval
        self._store: dict[int, dict] = {}
        self._wanted: set[int] = set()
        self._subscribed: set[int] = set()
        self._ws = None
        self._task: asyncio.Task[None] | None = None
        self._send_lock = asyncio.Lock()
        self._connected = False
        self._closing = False
        self._attempt = 0

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    def latest(self) -> dict[int, dict]:
        return {k: dict(v) for k, v in self._store.items()}

    def is_connected(self) -> bool:
        return self._connected

    async def set_instruments(self, ids: set[int]) -> None:
        ids = set(ids)
        self._wanted = ids
        ws = self._ws
        if ws is None or not self._connected:
            for gone in set(self._store) - ids:
                self._store.pop(gone, None)
            return
        add = ids - self._subscribed
        rem = self._subscribed - ids
        async with self._send_lock:
            if add:
                await ws.send(_envelope("Subscribe", {"topics": _topics(add), "snapshot": True}))
            if rem:
                await ws.send(_envelope("Unsubscribe", {"topics": _topics(rem)}))
        self._subscribed = ids
        for gone in rem:
            self._store.pop(gone, None)

    async def aclose(self) -> None:
        self._closing = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 — shutdown best-effort
                pass

    async def _run(self) -> None:
        while not self._closing:
            try:
                await self._connect_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — diverse ws/network errors
                log.warning("price stream error: %s", e)
            finally:
                self._connected = False
                self._ws = None
            if self._closing:
                break
            delay = self._backoff[min(self._attempt, len(self._backoff) - 1)]
            self._attempt += 1
            await asyncio.sleep(delay)

    async def _connect_once(self) -> None:
        async with connect(self._url, ping_interval=self._ping_interval, open_timeout=15) as ws:
            self._ws = ws
            self._subscribed = set()
            await ws.send(_envelope("Authenticate", {"userKey": self._uk, "apiKey": self._pk}))
            authed = False
            async for raw in ws:
                if isinstance(raw, bytes):  # server keepalive — ignore, never echo
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not authed:
                    if obj.get("operation") == "Authenticate":
                        if obj.get("success"):
                            authed = True
                            self._connected = True
                            self._attempt = 0
                            await self._subscribe_wanted(ws)
                        else:
                            code = obj.get("errorCode")
                            log.warning("ws auth failed: %s", code)
                            if code in _FATAL_AUTH_CODES:
                                self._closing = True
                            return
                    continue
                self._ingest(obj)

    async def _subscribe_wanted(self, ws) -> None:
        async with self._send_lock:
            if self._wanted:
                await ws.send(
                    _envelope("Subscribe", {"topics": _topics(self._wanted), "snapshot": True})
                )
            self._subscribed = set(self._wanted)

    def _ingest(self, obj: dict) -> None:
        messages = obj.get("messages")
        if not isinstance(messages, list):
            return
        for m in messages:
            topic = m.get("topic", "")
            if not topic.startswith("instrument:"):
                continue
            try:
                iid = int(topic.split(":", 1)[1])
            except (ValueError, IndexError):
                continue
            content = m.get("content")
            if not isinstance(content, str):
                continue
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                continue
            self._store[iid] = ws_content_to_rate(parsed, self._store.get(iid))
