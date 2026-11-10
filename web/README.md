# Web client

Next.js (App Router), TypeScript strict, plain CSS, no UI library. Structured answer on the left, evidence panel on the right, tabs Ask, Documents, Screening, KPIs and Market.

## Mock mode (default)

With `NEXT_PUBLIC_API_URL` empty or unset the client runs on the example payloads in `src/mock/`, with no network and no API. A badge in the header says `mock data`. Switching to `u_outsider` hides the deal, as the API does.

```
npm ci
npm run dev        # http://localhost:3000
```

## Against the API

```
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

The client sends the selected demo user in `X-User-Id` (DEMO_AUTH, not production authentication) and shows the `X-Ainma-Backend` header (`real` or `stub`) in the header badge. The API must allow the origin of the web client (`ALLOWED_ORIGINS`).

## Checks

```
npm run build && npm run lint && npm test
```

`npm test` replays `tests/fixtures/scoring_vectors.json` through the TypeScript `scoreCards`, compares the value contract with `src/ainma/contracts.py`, checks that `src/mock/*.json` equal their sources (refresh them with `npm run sync-mock`) and runs the one-click test: ask a question, click one citation, the cited span is marked in the evidence panel, with exactly one passage request.

An optional real browser version of that check is in `e2e/one-click.mjs` (Playwright is not a dependency, see the header of the file).
