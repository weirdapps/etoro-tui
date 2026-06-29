# WebSocket Price Stream Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace etoro-tui's REST price-polling with a real-time eToro WebSocket price stream, keeping the slow REST portfolio poll for structure + a REST-rates fallback.

**Architecture:** A new stateful `EtoroPriceStream` owns one WS connection (`wss://ws.etoro.com/ws`), authenticates, subscribes to `instrument:<id>` per held instrument, and maintains an in-memory rates store normalized to the existing REST `fetch_rates()` shape. `app.py` splits its single tick into a slow REST `_tick_portfolio` (structure + enrichment + subscription reconcile + REST fallback) and a fast `_tick_render` (rebuild positions from the live store). All existing downstream builders (`_to_position`, `_aggregate_by_symbol`, `_account_from`, `_previous_close_equity`) are reused unchanged.

**Tech Stack:** Python 3.13, Textual, httpx (REST, unchanged), **websockets>=13** (new), pytest + pytest-asyncio (`asyncio_mode=auto`) + respx, uv.

**Spec:** `docs/superpowers/specs/2026-06-29-websocket-migration-design.md`

## Global Constraints

- Python `target-version = py313`; ruff lint select `E,F,W,I,B,UP`, line-length 100; every module starts `from __future__ import annotations`.
- Tests: **no live network in CI.** HTTP → respx; WebSocket → a local in-process `websockets` server fixture. `asyncio_mode = "auto"` (the `@pytest.mark.asyncio` marker is still used by existing tests — match that style).
- WS protocol (verified live 2026-06-29): endpoint `wss://ws.etoro.com/ws`; auth `{"id":<uuid>,"operation":"Authenticate","data":{"userKey":<user_key>,"apiKey":<public_key>}}` → **`apiKey`=public_key, `userKey`=user_key**; **client sends TEXT only** (binary → `BinaryMessagesNotSupported`); server sends binary `\x00` keepalives the client **ignores**; inbound `{"messages":[{"topic","content":<escaped-JSON-string>,"id","type"}]}`; `snapshot:true` reply (`type:"Snapshot"`) carries `ConversionRateAsk/Bid`; deltas (`type:"Trading.Instrument.Rate"`) are price-only PascalCase (`Ask`,`Bid`,`LastExecution`,`Date`).
- Store output is **camelCase REST-shaped** (`lastExecution`,`ask`,`bid`,`conversionRateAsk`,`conversionRateBid`,`date`) so it is a drop-in for `_to_position`'s `rates` arg (consumed by `_extract_live_price`, which reads `lastExecution`/`Bid`/`bid` and `conversionRateAsk`).
- Keepalive: rely on the websockets library protocol ping (`ping_interval=20`); never send binary.
- Use the new asyncio API: `from websockets.asyncio.client import connect`; `from websockets.asyncio.server import serve` (tests). `from websockets.exceptions import ConnectionClosed`.
- Pinned knobs: render cadence default **1.5 s** (`[intervals].render`); kill-switch `[websocket].enabled` default **true**; no periodic re-snapshot in v1.
- Commit-message style ends with the repo's existing convention (Conventional Commits, e.g. `feat:`/`test:`/`docs:`). Branch first (currently on `master`): `git checkout -b feat/websocket-price-stream`.

## File Structure

- **Create** `src/etoro_tui/clients/price_stream.py` — `EtoroPriceStream` (stateful WS client + store) and pure `ws_content_to_rate()` adapter. One responsibility: turn the WS feed into a REST-shaped rates store.
- **Create** `tests/test_clients_price_stream.py` — adapter unit tests + stream tests against a local `websockets` server.
- **Create** `docs/etoro-websocket-actual.md` — verified protocol reference (mirrors `docs/etoro-api-actual.md`).
- **Modify** `src/etoro_tui/config.py` — add `WS_URL`, `WS_ENABLED`, `RENDER_S` (+ TOML overrides).
- **Modify** `src/etoro_tui/widgets/footer.py:83-91` — `watch_prices_source` accepts `"live (ws)"`/`"live (rest)"`/`"census"`.
- **Modify** `src/etoro_tui/app.py` — split `_tick_etoro` → `_tick_portfolio` + `_tick_render`; add `_rerender_positions`, `_current_rates`; cache render inputs; wire stream lifecycle; new `price_stream` ctor param.
- **Modify** `tests/test_app_logic.py` — add `_current_rates` / `_rerender_positions` tests.
- **Modify** `pyproject.toml` — add `websockets>=13` to `dependencies`; **regenerate** `uv.lock`.

---

### Task 1: Dependency + pure WS→rate adapter

**Files:**
- Modify: `pyproject.toml` (dependencies)
- Create: `src/etoro_tui/clients/price_stream.py`
- Create: `tests/test_clients_price_stream.py`

**Interfaces:**
- Produces: `ws_content_to_rate(content: dict, prev: dict | None) -> dict` — merges a parsed WS instrument-content dict (PascalCase) onto the previous REST-shaped rate dict; price/FX persist when a frame omits them; numeric fields become floats; `date` stays str.

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, change the `dependencies` array to include websockets:
```toml
dependencies = [
    "textual>=0.86",
    "httpx>=0.28",
    "yfinance>=0.2.40,<1.5",
    # Cross-platform credential storage (macOS Keychain, Windows Credential
    # Manager, Linux Secret Service). On Linux, SecretService backend needs dbus.
    "keyring>=24",
    # Real-time price stream (eToro WebSocket). asyncio-native; httpx can't do WS.
    "websockets>=13",
]
```

- [ ] **Step 2: Sync the environment**

Run: `cd ~/SourceCode/etoro-tui && uv lock && uv sync --extra dev`
Expected: `uv.lock` updated to include `websockets`; sync succeeds.

- [ ] **Step 3: Write the failing adapter tests**

Create `tests/test_clients_price_stream.py`:
```python
# tests/test_clients_price_stream.py
from etoro_tui.clients.price_stream import ws_content_to_rate

_SNAPSHOT = {
    "InstrumentID": "100000",
    "Ask": "100.5",
    "Bid": "100.4",
    "LastExecution": "100.45",
    "ConversionRateAsk": "1.1",
    "ConversionRateBid": "1.1",
    "Date": "2026-06-29T15:43:05Z",
}
_DELTA_PRICE = {
    "Ask": "101.0",
    "Bid": "100.9",
    "LastExecution": "100.95",
    "Date": "2026-06-29T15:43:06Z",
}
_DELTA_PRICELESS = {"Date": "2026-06-29T15:43:07Z", "PriceRateID": "999"}


def test_adapter_snapshot_produces_rest_camelcase_floats():
    out = ws_content_to_rate(_SNAPSHOT, None)
    assert out["lastExecution"] == 100.45
    assert out["ask"] == 100.5
    assert out["bid"] == 100.4
    assert out["conversionRateAsk"] == 1.1
    assert out["conversionRateBid"] == 1.1
    assert out["date"] == "2026-06-29T15:43:05Z"


def test_adapter_delta_keeps_conversion_rate_from_prev():
    prev = ws_content_to_rate(_SNAPSHOT, None)
    out = ws_content_to_rate(_DELTA_PRICE, prev)
    assert out["lastExecution"] == 100.95  # updated by delta
    assert out["conversionRateAsk"] == 1.1  # retained from snapshot (delta has no FX)


def test_adapter_priceless_frame_retains_prev_price():
    prev = ws_content_to_rate(_SNAPSHOT, None)
    out = ws_content_to_rate(_DELTA_PRICELESS, prev)
    assert out["lastExecution"] == 100.45  # unchanged
    assert out["conversionRateAsk"] == 1.1
    assert out["date"] == "2026-06-29T15:43:07Z"  # date advances


def test_adapter_tolerates_unparseable_numeric():
    out = ws_content_to_rate({"Ask": "not-a-number", "Bid": "5"}, None)
    assert "ask" not in out  # bad value skipped
    assert out["bid"] == 5.0
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `uv run pytest tests/test_clients_price_stream.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'etoro_tui.clients.price_stream'`.

- [ ] **Step 5: Implement the adapter**

Create `src/etoro_tui/clients/price_stream.py`:
```python
# src/etoro_tui/clients/price_stream.py
"""Real-time eToro price stream over WebSocket.

Replaces REST price polling with a push feed. Maintains an in-memory rates
store normalized to the REST `fetch_rates()` shape so the existing app pipeline
consumes it unchanged. See docs/etoro-websocket-actual.md for the verified
protocol.
"""

from __future__ import annotations

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
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_clients_price_stream.py -v`
Expected: PASS (4 passed).

- [ ] **Step 7: Lint + commit**

Run: `uv run ruff check src/etoro_tui/clients/price_stream.py tests/test_clients_price_stream.py && uv run ruff format --check src tests`
```bash
git add pyproject.toml uv.lock src/etoro_tui/clients/price_stream.py tests/test_clients_price_stream.py
git commit -m "feat: add websockets dep + WS->rate adapter"
```

---

### Task 2: `EtoroPriceStream` — connection, store, subscriptions, reconnect

**Files:**
- Modify: `src/etoro_tui/clients/price_stream.py`
- Modify: `tests/test_clients_price_stream.py`

**Interfaces:**
- Consumes: `ws_content_to_rate` (Task 1).
- Produces:
  - `class EtoroPriceStream` with `__init__(self, public_key: str, user_key: str, *, url: str = WS_URL, backoff_seconds: tuple[int, ...] = (5, 15, 60), ping_interval: float = 20.0)`.
  - `async def start(self) -> None` — spawn background connect/read loop.
  - `def latest(self) -> dict[int, dict]` — shallow copy of `{instrumentID: rate_dict}`.
  - `def is_connected(self) -> bool`.
  - `async def set_instruments(self, ids: set[int]) -> None` — reconcile subscriptions; drop store entries for removed ids.
  - `async def aclose(self) -> None`.
  - Module const `WS_URL = "wss://ws.etoro.com/ws"`.

- [ ] **Step 1: Write the failing stream tests**

Append to `tests/test_clients_price_stream.py`:
```python
import asyncio
import json

import pytest
from websockets.asyncio.server import serve

from etoro_tui.clients.price_stream import EtoroPriceStream


async def _wait_until(cond, timeout=3.0):
    loop_end = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < loop_end:
        if cond():
            return True
        await asyncio.sleep(0.02)
    return False


def _snapshot_frame(topic: str) -> str:
    content = {
        "InstrumentID": topic.split(":")[1],
        "Ask": "100.5", "Bid": "100.4", "LastExecution": "100.45",
        "ConversionRateAsk": "1.1", "ConversionRateBid": "1.1",
        "Date": "2026-06-29T15:43:05Z",
    }
    return json.dumps({"messages": [{"topic": topic, "content": json.dumps(content),
                                     "id": "s", "type": "Snapshot"}]})


def _delta_frame(topic: str) -> str:
    content = {"Ask": "101.0", "Bid": "100.9", "LastExecution": "100.95",
               "Date": "2026-06-29T15:43:06Z"}
    return json.dumps({"messages": [{"topic": topic, "content": json.dumps(content),
                                     "id": "d", "type": "Trading.Instrument.Rate"}]})


class _Server:
    """Local fake eToro WS. Captures client->server messages in `.received`."""

    def __init__(self):
        self.received: list[str] = []
        self.connections = 0
        self.drop_first = False

    async def handler(self, ws):
        self.connections += 1
        drop = self.drop_first and self.connections == 1
        async for raw in ws:
            self.received.append(raw)
            msg = json.loads(raw)
            op, rid = msg.get("operation"), msg.get("id")
            if op == "Authenticate":
                await ws.send(json.dumps({"id": rid, "success": True, "operation": "Authenticate"}))
                if drop:
                    await ws.close()
                    return
            elif op == "Subscribe":
                await ws.send(json.dumps({"id": rid, "success": True, "operation": "Subscribe"}))
                for topic in msg["data"]["topics"]:
                    await ws.send(b"\x00")           # binary keepalive — must be ignored
                    await ws.send(_snapshot_frame(topic))
                    await ws.send(_delta_frame(topic))
            elif op == "Unsubscribe":
                await ws.send(json.dumps({"id": rid, "success": True, "operation": "Unsubscribe"}))


async def _start_server(srv: _Server):
    server = await serve(srv.handler, "localhost", 0)
    port = server.sockets[0].getsockname()[1]
    return server, f"ws://localhost:{port}"


@pytest.mark.asyncio
async def test_stream_auth_subscribe_and_store():
    srv = _Server()
    server, url = await _start_server(srv)
    stream = EtoroPriceStream("pk", "uk", url=url, backoff_seconds=(0,))
    try:
        await stream.start()
        await stream.set_instruments({100000})
        assert await _wait_until(
            lambda: stream.latest().get(100000, {}).get("lastExecution") == 100.95
        )
        rate = stream.latest()[100000]
        assert rate["conversionRateAsk"] == 1.1   # snapshot FX retained over delta
        assert stream.is_connected() is True
        # auth used apiKey=public_key, userKey=user_key
        auth = json.loads(srv.received[0])
        assert auth["data"]["apiKey"] == "pk"
        assert auth["data"]["userKey"] == "uk"
    finally:
        await stream.aclose()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_stream_unsubscribe_drops_store_entry():
    srv = _Server()
    server, url = await _start_server(srv)
    stream = EtoroPriceStream("pk", "uk", url=url, backoff_seconds=(0,))
    try:
        await stream.start()
        await stream.set_instruments({100000, 1005})
        assert await _wait_until(lambda: 1005 in stream.latest() and 100000 in stream.latest())
        await stream.set_instruments({1005})
        assert await _wait_until(lambda: 100000 not in stream.latest())
        assert any('"Unsubscribe"' in m and "instrument:100000" in m for m in srv.received)
    finally:
        await stream.aclose()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_stream_reconnects_after_drop():
    srv = _Server()
    srv.drop_first = True
    server, url = await _start_server(srv)
    stream = EtoroPriceStream("pk", "uk", url=url, backoff_seconds=(0,))
    try:
        await stream.start()
        await stream.set_instruments({100000})
        assert await _wait_until(lambda: 100000 in stream.latest(), timeout=4.0)
        assert srv.connections >= 2  # dropped once, reconnected and re-subscribed
    finally:
        await stream.aclose()
        server.close()
        await server.wait_closed()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_clients_price_stream.py -k stream -v`
Expected: FAIL — `ImportError: cannot import name 'EtoroPriceStream'`.

- [ ] **Step 3: Implement the stream**

Append to `src/etoro_tui/clients/price_stream.py` (add imports at the top of the file alongside the existing `from __future__` line):
```python
import asyncio
import json
import logging
import uuid

from websockets.asyncio.client import connect

log = logging.getLogger(__name__)

WS_URL = "wss://ws.etoro.com/ws"

# Auth errors that mean "stop trying" rather than "back off and retry".
_FATAL_AUTH_CODES = {"Unauthorized", "InvalidKey", "Forbidden"}


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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_clients_price_stream.py -v`
Expected: PASS (all adapter + stream tests). If a timing-sensitive test flakes, the `_wait_until` timeout (3–4 s) covers CI; do not lower it.

- [ ] **Step 5: Lint + commit**

Run: `uv run ruff check src/etoro_tui/clients/price_stream.py tests/test_clients_price_stream.py`
```bash
git add src/etoro_tui/clients/price_stream.py tests/test_clients_price_stream.py
git commit -m "feat: EtoroPriceStream WS client with reconnect + subscription reconcile"
```

---

### Task 3: Config knobs + footer price-source label

**Files:**
- Modify: `src/etoro_tui/config.py`
- Modify: `src/etoro_tui/widgets/footer.py:83-91`
- Modify: `tests/test_config.py`

**Interfaces:**
- Produces: `config.WS_URL: str`, `config.WS_ENABLED: bool`, `config.RENDER_S: float`.
- Produces: `footer.prices_source` accepts `"live (ws)"`, `"live (rest)"`, `"census"`, `"—"`.

- [ ] **Step 1: Write the failing footer test**

Append to `tests/test_app_smoke.py`:
```python
@pytest.mark.asyncio
async def test_footer_prices_source_ws_label_is_green():
    app = EtoroTuiApp(initial_state=_make_state(), disable_polling=True)
    async with app.run_test() as pilot:
        await pilot.pause()
        footer = app.query_one("Footer")
        footer.prices_source = "live (ws)"
        await pilot.pause()
        rendered = app.query_one("#footer-prices")
        text = rendered.render()
        assert "live (ws)" in str(text)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_app_smoke.py::test_footer_prices_source_ws_label_is_green -v`
Expected: FAIL — current watcher only renders the literal value when `== "live"`; `"live (ws)"` falls to the dim else-branch but the text DOES contain "live (ws)"… so it may PASS by accident. To make the assertion meaningful, also assert the green style:
```python
        assert "green" in (str(text.style) + " " + " ".join(str(s.style) for s in text.spans))
```
Re-run: now FAIL (dim branch, not green).

- [ ] **Step 3: Update the footer watcher**

In `src/etoro_tui/widgets/footer.py`, replace `watch_prices_source` (lines ~83-91):
```python
    def watch_prices_source(self, value: str) -> None:
        # green=live (ws/rest), yellow=census fallback, dim=unknown.
        if value.startswith("live"):
            label = Text.assemble(("prices  ", "dim"), (f"● {value}", "green"))
        elif value.startswith("census"):
            label = Text.assemble(("prices  ", "dim"), ("● census fallback", "yellow"))
        else:
            label = Text.assemble(("prices  ", "dim"), (value, "dim"))
        self.query_one("#footer-prices", Static).update(label)
```

- [ ] **Step 4: Run the footer test to verify it passes**

Run: `uv run pytest tests/test_app_smoke.py::test_footer_prices_source_ws_label_is_green -v`
Expected: PASS.

- [ ] **Step 5: Add config knobs**

In `src/etoro_tui/config.py`, after the `ETORO_BASE_URL` line (~22) add:
```python
WS_URL = "wss://ws.etoro.com/ws"
WS_ENABLED = True  # [websocket].enabled — false forces the pure-REST path
```
In the refresh-intervals block (~25) add:
```python
RENDER_S = 1.5  # fast re-render cadence from the live WS store
```
In the "Apply TOML interval overrides" block (~165) add:
```python
RENDER_S = _toml("intervals", "render", default=RENDER_S)
WS_ENABLED = _toml("websocket", "enabled", default=WS_ENABLED)
```

- [ ] **Step 6: Write + run a config test**

Append to `tests/test_config.py`:
```python
def test_ws_defaults_present():
    from etoro_tui import config

    assert config.WS_URL.startswith("wss://")
    assert isinstance(config.WS_ENABLED, bool)
    assert config.RENDER_S > 0
```
Run: `uv run pytest tests/test_config.py::test_ws_defaults_present -v`
Expected: PASS.

- [ ] **Step 7: Lint + commit**

Run: `uv run ruff check src/etoro_tui/config.py src/etoro_tui/widgets/footer.py tests`
```bash
git add src/etoro_tui/config.py src/etoro_tui/widgets/footer.py tests/test_config.py tests/test_app_smoke.py
git commit -m "feat: config WS knobs + footer ws/rest price-source label"
```

---

### Task 4: app.py integration — split timers, live render, REST fallback

**Files:**
- Modify: `src/etoro_tui/app.py` (ctor ~387-409; `on_mount` ~419-442; `on_unmount` ~444-452; rename/split `_tick_etoro` ~456-561; `action_refresh` ~660-661)
- Modify: `tests/test_app_logic.py`

**Interfaces:**
- Consumes: `EtoroPriceStream` (Task 2), `config.WS_ENABLED`/`WS_URL`/`RENDER_S` (Task 3).
- Produces (new app methods/attrs, used by tests):
  - `EtoroTuiApp(..., price_stream: EtoroPriceStream | None = None)`.
  - `def _current_rates(self) -> dict[int, dict]` — WS store merged over `self._rest_rates` (WS wins); REST-only when store empty.
  - `def _rerender_positions(self) -> None` — rebuild from cached inputs + `_current_rates()`; render; set footer source from `self._prices_source`.
  - Cache attrs: `self._raw_positions`, `self._credit`, `self._instruments`, `self._fundamentals`, `self._pi_pct`, `self._yahoo_prev`, `self._inst_overrides`, `self._rest_rates`, `self._spark`, `self._prices_source`, `self._have_portfolio`.

- [ ] **Step 1: Write the failing integration tests**

Append to `tests/test_app_logic.py`:
```python
# ---------------------------------------------------------------------------
# WS price-stream integration: _current_rates + _rerender_positions
# ---------------------------------------------------------------------------

from etoro_tui.app import EtoroTuiApp


class _FakeStream:
    def __init__(self, rates: dict, connected: bool = True) -> None:
        self._rates = rates
        self._connected = connected
        self.instruments: set | None = None

    async def start(self) -> None: ...
    def latest(self) -> dict:
        return {k: dict(v) for k, v in self._rates.items()}
    def is_connected(self) -> bool:
        return self._connected
    async def set_instruments(self, ids: set) -> None:
        self.instruments = set(ids)
    async def aclose(self) -> None: ...


def test_current_rates_prefers_ws_over_rest():
    app = EtoroTuiApp(
        price_stream=_FakeStream({1005: {"lastExecution": 195.4, "conversionRateAsk": 1.0}}),
        disable_polling=True,
    )
    app._rest_rates = {1005: {"lastExecution": 190.0}, 1007: {"lastExecution": 50.0}}
    rates = app._current_rates()
    assert rates[1005]["lastExecution"] == 195.4  # WS wins
    assert rates[1007]["lastExecution"] == 50.0   # REST-only retained


def test_current_rates_falls_back_to_rest_when_ws_empty():
    app = EtoroTuiApp(price_stream=_FakeStream({}, connected=False), disable_polling=True)
    app._rest_rates = {1005: {"lastExecution": 190.0}}
    assert app._current_rates()[1005]["lastExecution"] == 190.0


@pytest.mark.asyncio
async def test_rerender_builds_positions_from_ws_store():
    from etoro_tui.clients.census import InstrumentInfo

    app = EtoroTuiApp(
        initial_state=None,
        disable_polling=True,
        price_stream=_FakeStream({1001: {"lastExecution": 195.40, "conversionRateAsk": 1.0}}),
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        app._have_portfolio = True
        app._raw_positions = [{
            "positionID": 42, "instrumentID": 1001, "units": 10.0, "openRate": 150.0,
            "openConversionRate": 1.0, "isBuy": True, "openDateTime": "2026-01-01T10:00:00.000Z",
        }]
        app._instruments = {1001: InstrumentInfo(symbol="AAPL", current_price=200.0)}
        app._credit = 1000.0
        app._prices_source = "live (ws)"
        app._rerender_positions()
        await pilot.pause()
        table = app.query_one("PositionsTable")
        assert any(abs(p.current_rate - 195.40) < 1e-6 for p in table.positions)
        assert "live (ws)" in str(app.query_one("#footer-prices").render())
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_app_logic.py -k "current_rates or rerender" -v`
Expected: FAIL — `EtoroTuiApp.__init__() got an unexpected keyword argument 'price_stream'`.

- [ ] **Step 3: Update the constructor + imports**

In `src/etoro_tui/app.py`, add the import near the other client imports (~22-26):
```python
from .clients.price_stream import EtoroPriceStream
```
Change `__init__` signature + body (~387-409) to add the param and cache attrs:
```python
    def __init__(
        self,
        initial_state: AppState | None = None,
        disable_polling: bool = False,
        etoro_client: EtoroClient | None = None,
        price_stream: EtoroPriceStream | None = None,
    ) -> None:
        super().__init__()
        self._state: AppState = initial_state or AppState(
            account=None, positions=(), last_error=None, status="live", equity_sparkline=(),
        )
        self._disable_polling = disable_polling
        self._etoro_client = etoro_client
        self._price_stream = price_stream
        self._signals = SignalsReader(config.SIGNALS_CSV)
        self._census = CensusReader(config.CENSUS_GLOB_DIR, config.CENSUS_GLOB_PATTERN)
        self._yahoo = YahooClient(ttl_seconds=1800)
        self._db: sqlite3.Connection | None = None
        self._fetch_task: asyncio.Task[None] | None = None
        self._etoro_timer: Timer | None = None
        self._render_timer: Timer | None = None
        self._market_open: bool = config.is_market_active()
        # Render-input cache: _tick_portfolio (slow REST) fills these; _tick_render
        # (fast) rebuilds positions from them + the live WS store.
        self._raw_positions: list[dict] = []
        self._credit: float = 0.0
        self._instruments: dict[int, InstrumentInfo] = {}
        self._fundamentals: dict[str, Fundamentals] = {}
        self._pi_pct: dict = {}
        self._yahoo_prev: dict[str, float] = {}
        self._inst_overrides: dict[int, str] = {}
        self._rest_rates: dict[int, dict] = {}
        self._spark: tuple[float, ...] = ()
        self._prices_source: str = "—"
        self._have_portfolio: bool = False
```

- [ ] **Step 4: Add `_current_rates` + `_rerender_positions`**

In `src/etoro_tui/app.py`, add these methods to `EtoroTuiApp` (place them just before `_tick_etoro`, ~455):
```python
    def _current_rates(self) -> dict[int, dict]:
        """Live WS rates merged over the REST fallback (WS wins per instrument)."""
        ws = self._price_stream.latest() if self._price_stream is not None else {}
        if ws:
            merged = dict(self._rest_rates)
            merged.update(ws)
            return merged
        return self._rest_rates

    def _rerender_positions(self) -> None:
        """Rebuild Positions from cached portfolio + enrichment + current rates."""
        if not self._have_portfolio:
            return
        rates = self._current_rates()
        positions_list: list[Position] = []
        for raw in self._raw_positions:
            built = _to_position(
                raw, self._instruments, self._fundamentals, self._pi_pct,
                rates, self._yahoo_prev, self._inst_overrides,
            )
            if built is not None:
                positions_list.append(built)
        positions = _aggregate_by_symbol(positions_list)
        acct = _account_from(positions, self._credit)
        live = bool(rates)
        self._state = AppState(
            account=acct, positions=positions, last_error=None,
            status="live" if live else "degraded", equity_sparkline=self._spark,
        )
        footer = self.query_one(Footer)
        footer.prices_source = self._prices_source
        footer.census_stale = self._census.is_stale
        self._render_state()
```

- [ ] **Step 5: Split `_tick_etoro` into `_tick_portfolio` + `_tick_render`**

In `src/etoro_tui/app.py`, replace the whole `_tick_etoro` method (~456-561) with the two methods below. `_tick_portfolio` keeps the existing fetch + enrichment logic but caches inputs, chooses WS-vs-REST rates, reconciles subscriptions, and delegates rendering to `_rerender_positions`:
```python
    async def _tick_portfolio(self) -> None:
        # Track ourselves so on_unmount can cancel an in-flight fetch.
        self._fetch_task = asyncio.current_task()
        if self._etoro_client is None:
            return
        try:
            portfolio = await self._etoro_client.fetch_portfolio()
        except EtoroAuthError as e:
            self._set_error(f"auth failed: {e}", "down")
            return
        except EtoroTransientError as e:
            self._set_error(f"transient: {e}", "degraded")
            return

        self._raw_positions = portfolio.get("positions", [])
        self._credit = float(portfolio.get("credit", 0.0))
        self._instruments = self._census.instruments()
        unique_ids = sorted({raw["instrumentID"] for raw in self._raw_positions})

        # Reconcile WS subscriptions to exactly what we hold.
        if self._price_stream is not None and unique_ids:
            await self._price_stream.set_instruments(set(unique_ids))

        # Choose price source. WS is authoritative when connected AND it has
        # ticks for us; otherwise fall back to the REST rates endpoint, then to
        # census (handled downstream in _to_position).
        ws_live = (
            self._price_stream is not None
            and self._price_stream.is_connected()
            and bool(self._price_stream.latest())
        )
        if ws_live:
            self._rest_rates = {}
            self._prices_source = "live (ws)"
        elif unique_ids:
            try:
                self._rest_rates = await self._etoro_client.fetch_rates(unique_ids)
            except EtoroAuthError as e:
                self._set_error(f"auth failed (rates): {e}", "down")
                return
            except EtoroTransientError as e:
                log.warning("rates fetch failed, using census fallback: %s", e)
                self._rest_rates = {}
            self._prices_source = "live (rest)" if self._rest_rates else "census"
        else:
            self._rest_rates = {}
            self._prices_source = "census"

        self._fundamentals = self._signals.fundamentals()
        self._pi_pct = self._census.read()
        self._inst_overrides = config.get_instrument_overrides()

        all_syms_set: set[str] = set()
        for iid in unique_ids:
            if iid in self._instruments:
                all_syms_set.add(self._instruments[iid].symbol)
            elif iid in self._inst_overrides:
                all_syms_set.add(self._inst_overrides[iid])
        try:
            self._yahoo_prev = await self._yahoo.fetch_prev_closes(sorted(all_syms_set))
        except Exception as e:  # noqa: BLE001 — yfinance throws diverse exceptions
            log.warning("yahoo fetch failed, using census fallback: %s", e)
            self._yahoo_prev = {}

        if self._db is not None:
            self._spark = storage.read_equity_sparkline(self._db, hours=4, max_points=24)

        index_specs = config.get_indices()
        index_quotes = await self._yahoo.fetch_index_quotes([sym for _, sym in index_specs])
        self.query_one(Header).indices = _build_indices(index_specs, index_quotes)

        self._have_portfolio = True
        self._rerender_positions()
        self._adjust_poll_interval()

    def _tick_render(self) -> None:
        # Fast path: repaint P&L from the live WS store, no network. Cached
        # enrichment from the last _tick_portfolio is reused.
        self._rerender_positions()
```

Note: `_adjust_poll_interval` (~563-574) currently rebinds `self._etoro_timer = self.set_interval(new_s, self._tick_etoro)`. Update that single reference from `self._tick_etoro` to `self._tick_portfolio`.

- [ ] **Step 6: Wire stream lifecycle into `on_mount` / `on_unmount` / `action_refresh`**

In `on_mount` (~419-442), replace the polling-setup tail (from `if self._etoro_client is None:` onward) with:
```python
        if self._etoro_client is None or (self._price_stream is None and config.WS_ENABLED):
            try:
                pk, uk = config.get_credentials()
            except config.AuthMissingError as e:
                self._set_error(str(e), "down")
                return
            if self._etoro_client is None:
                self._etoro_client = EtoroClient(public_key=pk, user_key=uk)
            if self._price_stream is None and config.WS_ENABLED:
                self._price_stream = EtoroPriceStream(public_key=pk, user_key=uk)
        if self._price_stream is not None:
            await self._price_stream.start()
        poll_s = config.POLL_PORTFOLIO_S if self._market_open else config.POLL_PORTFOLIO_IDLE_S
        self._etoro_timer = self.set_interval(poll_s, self._tick_portfolio)
        if self._price_stream is not None:
            self._render_timer = self.set_interval(config.RENDER_S, self._tick_render)
        self.set_interval(config.POLL_SIGNALS_S, self._tick_overlays)
        self.set_interval(config.SNAPSHOT_S, self._tick_snapshot)
        self.set_interval(1.0, self._tick_footer_clock)
        self._fetch_task = asyncio.create_task(self._tick_portfolio())
```
In `on_unmount` (~444-452), add stream close before the client close:
```python
        if self._price_stream is not None:
            await self._price_stream.aclose()
```
In `action_refresh` (~660-661), change the call:
```python
    async def action_refresh(self) -> None:
        await self._tick_portfolio()
```

- [ ] **Step 7: Run the integration tests + full suite**

Run: `uv run pytest tests/test_app_logic.py -k "current_rates or rerender" -v`
Expected: PASS.
Run: `uv run pytest -q`
Expected: entire suite PASS (existing tests unaffected; the `_tick_overlays`/`_tick_snapshot`/`_tick_footer_clock` timers and downstream builders are untouched).

- [ ] **Step 8: Lint + commit**

Run: `uv run ruff check src/etoro_tui/app.py tests/test_app_logic.py`
```bash
git add src/etoro_tui/app.py tests/test_app_logic.py
git commit -m "feat: drive live prices from WS stream with REST fallback"
```

---

### Task 5: Protocol doc + final verification

**Files:**
- Create: `docs/etoro-websocket-actual.md`
- Modify: `README.md` (one line under data sources, optional)

- [ ] **Step 1: Write the verified-protocol doc**

Create `docs/etoro-websocket-actual.md`:
```markdown
# eToro WebSocket API — Actual Behavior (verified 2026-06-29)

Live probe against `wss://ws.etoro.com/ws` (read-only: public instrument feed only).
Supersedes the published doc where they conflict.

## Connection & auth
- Endpoint: `wss://ws.etoro.com/ws` (Cloudflare-fronted), no subprotocol.
- Auth message (TEXT): `{"id":<uuid>,"operation":"Authenticate","data":{"userKey":<USER_KEY>,"apiKey":<PUBLIC_KEY>}}`
  - **`apiKey` = public_key (REST `x-api-key`), `userKey` = user_key (REST `x-user-key`).**
  - Success: `{"id":<uuid>,"success":true,"operation":"Authenticate"}`.
  - Failure adds `errorMessage` + `errorCode` (e.g. `Unauthorized`, `InvalidKey`, `TooManyRequests`).

## Framing
- **Client may send TEXT frames only.** A binary frame → `{"success":false,"errorCode":"BinaryMessagesNotSupported"}`.
- The server emits periodic **binary `\x00` keepalive frames** — ignore them; never echo.
- Keepalive from the client: rely on the WS protocol-level ping (control frame), not application data.

## Subscribe / unsubscribe
- `{"id":<uuid>,"operation":"Subscribe","data":{"topics":["instrument:<id>"],"snapshot":true}}`
- `{"id":<uuid>,"operation":"Unsubscribe","data":{"topics":["instrument:<id>"]}}`
- Ack: `{"id":<uuid>,"success":true,"operation":"Subscribe"}`.

## Inbound data
- Envelope: `{"messages":[{"topic":"instrument:<id>","content":<escaped-JSON-string>,"id":<uuid>,"type":<str>}]}`.
- `content` is a **JSON-escaped string** → parse twice.
- `type:"Snapshot"` (sent once on subscribe with `snapshot:true`) — FULL state incl.
  `ConversionRateAsk`, `ConversionRateBid`, `Ask`, `Bid`, `LastExecution`, `OfficialClosingPrice`,
  `DailyClose`, `Date`, `IsMarketOpen`.
- `type:"Trading.Instrument.Rate"` (deltas) — **price-only**, PascalCase: `Ask`, `Bid`,
  `LastExecution`, `Date`, `PriceRateID`. **No ConversionRate.** Some deltas are price-less (`{Date,PriceRateID}`).
- Field casing is **PascalCase** (REST is camelCase). Cadence: BTC ~0.3–1.5 s.

## Implications for etoro-tui
1. The conversion rate (FX) arrives only in the snapshot → the client caches it per instrument
   and merges onto price-only deltas. WS is self-sufficient for FX.
2. Normalize WS PascalCase → REST camelCase so the existing pipeline consumes it unchanged.
3. REST `fetch_rates` is retained only as a fallback when the socket is down.

## Not covered / future
- `private` topic (real-time position open/close) — not yet used.
- `OfficialClosingPrice`/`DailyClose` could replace the Yahoo prev-close dependency.
```

- [ ] **Step 2: Full verification sweep**

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run pytest -q`
Expected: ruff clean, formatter clean, all tests PASS.

- [ ] **Step 3: Manual live smoke (optional, requires creds)**

Run: `uv run etoro-tui` (with eToro keys in keychain/env). Expected: footer shows `prices ● live (ws)` within a few seconds; P&L updates sub-second for liquid holdings; killing network briefly → reconnect (footer may flicker to `census`/`live (rest)` then back to `live (ws)`).

- [ ] **Step 4: Commit**

```bash
git add docs/etoro-websocket-actual.md README.md
git commit -m "docs: verified eToro WebSocket protocol reference"
```

---

## Self-Review

**1. Spec coverage**

| Spec section | Task(s) |
|---|---|
| Verified protocol (auth map, framing, snapshot/delta, FX) | Task 2 (impl), Task 5 (doc) |
| `EtoroPriceStream` (store, set_instruments, latest, is_connected, reconnect, keepalive, binary-ignore) | Task 2 |
| Pure adapter (PascalCase→camelCase, OCR merge, price-less tolerance) | Task 1 |
| app.py split (`_tick_portfolio`/`_tick_render`), reuse downstream builders, fallback trigger, footer source | Task 4 |
| Config knobs (render cadence, `[websocket].enabled`) | Task 3 |
| Testing (adapter, stream via local server, app integration, no live CI) | Tasks 1,2,4 |
| New dep `websockets>=13` | Task 1 |
| Graceful degradation (WS down → REST → census) | Task 4 (`_current_rates`, fallback branch) + existing `_to_position` |

No spec requirement is left without a task.

**2. Placeholder scan** — none. Every code/test step contains complete code; every run step has an exact command + expected result.

**3. Type consistency** — `EtoroPriceStream.latest()` returns `dict[int, dict]` (used by `_current_rates`); `set_instruments(set[int])` (called with `set(unique_ids)`); `ws_content_to_rate(content, prev)` signature identical across Tasks 1–2; footer `prices_source` string values (`"live (ws)"`/`"live (rest)"`/`"census"`) match what Task 4 sets and Task 3 renders; `_to_position` call signature matches the existing definition (`raw, instruments, fundamentals, pi_pct, rates, yahoo_prev, instrument_overrides`).
