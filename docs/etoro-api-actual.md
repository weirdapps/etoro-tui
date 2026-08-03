# eToro Public API — Actual Behavior (Discovered 2026-05-05)

## Summary

Field/endpoint reference for the eToro Public API as observed in practice.
Account-identifying values in the example response below are SYNTHETIC —
do not treat them as a real position.

> **Corrections since the original probe.** Two findings from the 2026-06-30
> follow-up invalidated part of the first pass:
>
> 1. eToro returns `403 Forbidden` to any request without a browser-like
>    `User-Agent`. The first probe sent none, so some "dead" endpoints were
>    never actually reached.
> 2. The base URL already ends in `/api/public`, so request paths start at
>    `/v1/`. Paths written as `/api/v1/...` produce a doubled `/api/` and 404.
>
> With both corrected, the `market-data` endpoints work and are what the app
> uses for live prices today. Paths below are relative to the base URL.

## Base URL

| Documented (wrong) | Actual |
|---|---|
| `https://api.etoro.com` | **`https://www.etoro.com/api/public`** |

The wrong host returns generic `{"statusCode":404,"message":"Resource not found"}` for every path — the host is reachable but it's NOT the API host.

## Headers

- `x-api-key: <PUBLIC_KEY>`
- `x-user-key: <USER_KEY>`
- `x-request-id: <UUID>`
- `Content-Type: application/json`
- `User-Agent: <browser-like string>`: **required**. Without it eToro answers `403 Forbidden` on every path.

## Working Endpoints (verified)

### `GET /v1/trading/info/portfolio`: main endpoint

Returns ONE blob with everything: positions, cash, orders. There is no separate `/account` endpoint that we can find.

```json
{
  "clientPortfolio": {
    "positions": [
      {
        "positionID": 0,                          // <redacted — int>
        "CID": 0,                                 // <redacted — int customer id>
        "openDateTime": "2026-01-01T00:00:00Z",   // <synthetic>
        "openRate": 100.00,                       // <synthetic>
        "instrumentID": 1005,                     // AAPL (public mapping)
        "isBuy": true,
        "takeProfitRate": 0.0,
        "stopLossRate": 0.0001,
        "amount": 1000.0,                         // <synthetic — invested USD>
        "leverage": 1,
        "units": 10.0,                            // <synthetic>
        "totalFees": 0.0,
        "initialAmountInDollars": 1000.0          // <synthetic>
        // ... ~25 other internal fields
      }
    ],
    "credit": 0.00,                               // <redacted — cash USD>
    "bonusCredit": 0.0,
    "mirrors": [],
    "orders": [],
    "stockOrders": [],
    "entryOrders": [],
    "exitOrders": [],
    "ordersForOpen": [],
    "ordersForClose": [],
    "ordersForCloseMultiple": []
  }
}
```

### `GET /v1/market-data/instruments/rates?instrumentIds=…`: live prices

Last / bid / ask plus `conversionRateAsk` (FX to USD) per instrument. This is
the REST price path, used whenever the WebSocket stream is not connected.
Batched by the client.

### `GET /v1/market-data/instruments?instrumentIds=…`: symbol resolution

Resolves an `instrumentID` to a ticker for positions the census does not cover.

### `GET /v1/watchlists`: also works

Not used by etoro-tui but confirms auth is correct.

## What's MISSING from the API response

The position records do NOT include:
- `symbol` — only `instrumentID` (resolve via census `instruments.details[]`)
- `currentRate`: current price not provided (use the WebSocket stream or `/v1/market-data/instruments/rates`; census `instruments.priceData[]` is the last-resort fallback)
- `profit` — must compute locally
- `profitPercentage` — must compute locally
- `value` — must compute locally (`units * current_price`)

## Endpoints that returned 404 in the original probe

Probed 2026-05-05 with the doubled `/api/` prefix and no `User-Agent`. All
variants returned `{"errorCode":"RouteNotFound"}`:
- `/api/v1/account`, `/api/v1/Equity/{Real,real}`, `/api/v1/Credit/{Real,real}`
- `/api/v1/instruments`, `/api/v1/instruments/{id}`
- `/api/v1/market-data/*`
- `/api/v1/trading/positions`, `/api/v1/trading/info/{equity,balance,account}`
- And ~15 other guesses

`market-data` has since been re-probed at the corrected `/v1/` prefix with a
User-Agent and works (see above). The others have **not** been re-probed, so
read this list as "unproven", not "confirmed dead".

The `api-portal.etoro.com` docs reference `/Credit/{System}` and `/Equity/{System}` endpoints but neither responds with our credentials. May be partner-tier only.

## Implications for etoro-tui

1. **Symbol lookup** uses census `instruments.details[]`, with `/v1/market-data/instruments` resolving IDs the census does not carry.
2. **Current price** comes from the WebSocket stream, then `/v1/market-data/instruments/rates`, and only falls back to census `instruments.priceData[]` (daily, ~03:00 UTC) when both are unavailable.
3. **P&L computation** is local: `pnl = (current_price - openRate) * units * (1 if isBuy else -1)`.
4. **Equity** is local: `sum(position.value) + credit`.
5. **One fetch per tick** instead of two (no separate /account call).

## Future work

- The published eToro API may add more endpoints over time. Re-probe quarterly.
