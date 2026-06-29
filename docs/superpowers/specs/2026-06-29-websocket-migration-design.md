# WebSocket Price Migration — Design

**Date:** 2026-06-29
**Status:** Approved (design), pending implementation plan
**Scope choice:** Prices via WebSocket + slow REST portfolio poll + REST rates as fallback (hybrid). `private` topic explicitly OUT of scope.

## Problem

`etoro-tui` advertises "live portfolio" but prices are **polled**. Every `POLL_PORTFOLIO_S` (30 s, market hours) `_tick_etoro()` makes two REST calls:

1. `GET /api/v1/trading/info/portfolio` — positions + credit (portfolio *structure*)
2. `GET /api/v1/market-data/instruments/rates?instrumentIds=…` — live bid/ask/last + FX per held instrument (*prices*)

…then enriches with census/signals/yahoo and re-renders. "Live" means "≤30 s stale." eToro exposes a WebSocket that pushes real-time price ticks, so we can make the price half genuinely live.

## Verified protocol (live probe, 2026-06-29, read-only)

Probed `wss://ws.etoro.com/ws` against the real account (BTC public price feed only — never the authenticated `private` topic). Findings (these supersede the published doc where they conflict):

| Aspect | Verified behaviour |
|---|---|
| Endpoint | `wss://ws.etoro.com/ws` (Cloudflare-fronted), no negotiated subprotocol |
| Auth | Send `{"id":<uuid>,"operation":"Authenticate","data":{"userKey":<user_key>,"apiKey":<public_key>}}`. **`apiKey` = public_key, `userKey` = user_key** (same keys as REST `x-api-key`/`x-user-key`). Reply: `{"id":<uuid>,"success":true,"operation":"Authenticate"}` |
| Framing | **Client may send TEXT frames only.** A binary frame → `{"success":false,"errorCode":"BinaryMessagesNotSupported"}`. The server emits periodic **binary `\x00` keepalive frames**; the client MUST ignore them and MUST NOT echo them |
| Keepalive | Rely on the WS library's protocol-level ping (control frame — accepted). Ignore the server's application `\x00` frames |
| Subscribe | `{"id":<uuid>,"operation":"Subscribe","data":{"topics":["instrument:100000"],"snapshot":true}}` → `{"id":<uuid>,"success":true,"operation":"Subscribe"}` |
| Inbound envelope | `{"messages":[{"topic":"instrument:<id>","content":<escaped-JSON-string>,"id":<uuid>,"type":<str>}]}`. `content` is a **JSON-escaped string** → double-parse |
| Snapshot frame | `type:"Snapshot"` — FULL state incl. `ConversionRateAsk`, `ConversionRateBid`, `Ask`, `Bid`, `LastExecution`, `OfficialClosingPrice`, `DailyClose`, `Date`, `IsMarketOpen`, … |
| Delta frame | `type:"Trading.Instrument.Rate"` — **price-only**: `Ask`, `Bid`, `LastExecution`, `Date`, `PriceRateID`, margin fields. **No ConversionRate.** Some deltas are price-less (`{Date,PriceRateID}` only) |
| FX | **Available via WS** — `ConversionRate*` arrives in the Snapshot, not in deltas. Client caches it from the snapshot and merges onto every delta |
| Field casing | WS = **PascalCase** (`Ask`,`LastExecution`,`ConversionRateAsk`,`InstrumentID`). REST = camelCase (`ask`,`lastExecution`,`conversionRateAsk`,`instrumentID`). Adapter normalizes WS→camelCase |
| Cadence | BTC ~0.3–1.5 s between ticks |
| Rate limit | Only `TooManyRequests` documented (on auth). None hit during probe |

**Load-bearing fact:** snapshot carries FX + closing price *once*; deltas are price-only thereafter. The client must be **stateful** — cache per-instrument conversion rate from the snapshot, merge onto deltas. This makes the WebSocket self-sufficient for FX; REST rates are needed only as a fallback.

The raw probe evidence will be committed as `docs/etoro-websocket-actual.md` (mirroring `docs/etoro-api-actual.md`).

## Goals / Non-goals

**Goals**
- Replace the REST price-polling half with a real-time WS price stream.
- Reuse the entire downstream pipeline (`_to_position`, `_aggregate_by_symbol`, `_account_from`, `_previous_close_equity`) unchanged.
- Graceful degradation: WS down → REST `fetch_rates` fallback → census; the TUI never goes dark.
- No regressions in existing tests; new logic covered by TDD with no live calls in CI.

**Non-goals (noted, not built)**
- `private` topic (real-time position open/close). Future follow-up.
- Using WS `OfficialClosingPrice`/`DailyClose` to drop the Yahoo prev-close dependency. Future follow-up.
- Changing the TUI layout / widgets. Purely a data-source migration.

## Architecture

Two new units + surgical `app.py` changes.

### Unit 1 — `clients/price_stream.py :: EtoroPriceStream` (stateful)

Owns one WS connection and an in-memory rates store.

**Responsibilities**
- Connect → `Authenticate` → `Subscribe` to `instrument:<id>` for each held ID with `snapshot:true`.
- Maintain `dict[int, dict]` of latest rates, **normalized to the REST camelCase shape** so it is a drop-in for `EtoroClient.fetch_rates()` output:
  `{instrumentID: {"lastExecution","ask","bid","conversionRateAsk","conversionRateBid","date"}}`.
- Cache `ConversionRate*` from the snapshot; merge onto price-only deltas.
- Auto-reconnect with exponential backoff; on reconnect re-auth + re-subscribe (snapshot refreshes FX).
- WS-library ping for keepalive; ignore binary frames; never send binary.

**Interface**
```python
class EtoroPriceStream:
    def __init__(self, public_key: str, user_key: str, *, url: str = WS_URL,
                 backoff_seconds: tuple[int, ...] = (5, 15, 60)) -> None: ...
    async def start(self) -> None:        # spawn the background connect/read loop
    async def set_instruments(self, ids: set[int]) -> None:  # reconcile sub/unsub
    def latest(self) -> dict[int, dict]:  # sync snapshot of the store (no await)
    def is_connected(self) -> bool: ...
    async def aclose(self) -> None: ...
```
- `latest()` is synchronous and side-effect-free — the render loop calls it without awaiting.
- All exceptions are contained inside the background task; failures flip `is_connected()` to False and trigger reconnect. They never propagate into the TUI.

### Unit 2 — pure adapter (in `price_stream.py`)

```python
def ws_content_to_rate(content: dict, prev: dict | None) -> dict:
    """PascalCase WS content -> camelCase REST-shaped rate dict.
    Merges cached conversion rate from `prev` when the delta omits it.
    Tolerates price-less frames (returns prev unchanged if no price)."""
```
Pure function → unit-tested in isolation (snapshot parse, delta merge, price-less tolerance, casing).

### Unit 3 — `app.py` integration

Split today's `_tick_etoro` into two timers; downstream builders untouched.

- **`_tick_portfolio`** (REST, every `POLL_PORTFOLIO_S`): `fetch_portfolio()` → cache `raw_positions`, `credit`, and enrichment inputs (census instruments, fundamentals, pi_pct, yahoo_prev, indices) on `self`. Then `await price_stream.set_instruments(held_ids)`. **Fallback trigger (precise):** call REST `fetch_rates(held_ids)` when `not price_stream.is_connected()` OR the store has zero entries for the held set; merge REST rates under any WS rates already present (WS wins). This is the same `fetch_rates` path as today, now demoted to a safety net.
- **`_tick_render`** (fast, ~1.5 s): if cached portfolio exists, rebuild Positions from cached raw + enrichment + `price_stream.latest()`, recompute account, re-render. No network. This is the "live" feel.
- Footer price source: `live (ws)` when store fresh, `live (rest)` on fallback, `census` when neither.
- Lifecycle: build + `start()` the stream in `on_mount` (after credentials resolve); `aclose()` in `on_unmount`.

A small render-input cache on `self` lets `_tick_render` reuse enrichment without re-hitting census/signals/yahoo every 1.5 s.

## Data flow

```
REST /portfolio (POLL_PORTFOLIO_S) ─► raw positions + credit + held_ids ─► set_instruments()
                                                                               │
WS instrument:<id> snapshot+deltas ─► EtoroPriceStream.store {id: rate} ◄──────┘
                                            │
_tick_render (~1.5s): cached raw + store.latest() ─► _to_position ─► _aggregate ─► render
                                            │ (store empty / WS down)
                                            └─► fallback: REST fetch_rates()
```

## Error handling

| Condition | Behaviour |
|---|---|
| WS connect/read error | Contained in background task; `is_connected()=False`; reconnect w/ backoff (5/15/60 s cap) |
| Reconnect | Re-`Authenticate` then re-`Subscribe` all held IDs (snapshot → fresh FX) |
| Auth failure (`Unauthorized`/`InvalidKey`) | Surface to footer; stop retrying auth (no infinite loop); REST fallback continues |
| `TooManyRequests` on auth | Back off and retry per backoff schedule |
| Binary `\x00` frame | Ignored (never echoed) |
| Price-less delta | Ignored; last price retained |
| Store empty for a held ID | `_to_position` already falls back to census price (existing behaviour) |

## Testing (TDD)

No live network in CI. New dep: `websockets>=13` (asyncio-native; httpx can't do WS).

1. **Pure adapter** (`ws_content_to_rate`): snapshot→camelCase; delta merges cached OCR; price-less frame returns prev; casing normalization; missing fields tolerated.
2. **Price store / stream**: against a **local in-process `websockets` server** fixture that mimics the verified handshake (auth ok, subscribe ok, snapshot then deltas, a binary `\x00`). Assert: `latest()` shape == REST shape; OCR merged; `set_instruments` adds/removes subscriptions; reconnect re-subscribes; binary ignored.
3. **app.py integration**: `_tick_render` builds positions from a stubbed `price_stream.latest()` (injected fake) without network; fallback path calls `fetch_rates` when store empty. Existing `_to_position`/aggregate/account tests stay green.
4. **Regression**: full existing suite green; `disable_polling` test path unaffected.

## Rollout / safety

- New code is additive; REST path remains as fallback, so a WS outage degrades rather than breaks.
- New code is additive; REST path remains as fallback, so a WS outage degrades rather than breaks.

## Decisions pinned for implementation

- **Fast-render cadence:** default **1.5 s**, configurable via TOML `[intervals].render`.
- **Kill-switch:** include `[websocket] enabled` (default `true`). `false` forces the pure-REST path — cheap release insurance, matches the app's config-driven style.
- **FX freshness:** rely on snapshot-at-subscribe + re-snapshot-on-reconnect; **no periodic re-snapshot in v1** (intraday FX drift is small; the REST fallback covers degenerate cases). YAGNI until a long-session FX-drift problem is observed.
