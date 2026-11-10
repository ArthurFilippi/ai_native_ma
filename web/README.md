# Web client

Next.js (App Router), TypeScript strict, plain CSS, no UI library. Four pages: Deal (data room and key figures), Ask (a chat where each answer shows the answer, a confidence level and numbered sources; one click opens the passage), Buyers (pre-selection form, refine in words, results with fit, confidence, sources and risk flags) and Market (news events). The look comes from `public/ui.css` (the design system, unchanged, see `design/DESIGN.md`) and `src/app/app.css`.

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

The client sends the selected demo user in `X-User-Id` (DEMO_AUTH, not production authentication) and the header badge reads `real` (served by the API) or `mock data` (mock mode). The API must allow the origin of the web client (`ALLOWED_ORIGINS`).

## Checks

```
npm run build && npm run lint && npm test
```

`npm test` replays `tests/fixtures/scoring_vectors.json` through the TypeScript `scoreCards`, compares the value contract with `src/ainma/contracts.py`, checks that `src/mock/*.json` equal their sources (refresh them with `npm run sync-mock`) and runs the one-click test: ask a question, click one citation, the cited span is marked in the evidence panel, with exactly one passage request.

An optional real browser version of that check is in `e2e/one-click.mjs` (Playwright is not a dependency, see the header of the file).
