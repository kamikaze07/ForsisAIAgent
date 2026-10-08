# Omniroute Configuration

## Endpoint
- **Base URL:** http://forsispr1.ddns.net:20130/
- **Combo name:** Forsis
- **Status:** HTTP 307 redirect confirmed (active)

## Notes
- Port 20130 is the only responding endpoint (20129 accepts TCP but doesn't respond)
- API authentication and exact request format to be determined in Phase 1

## CORRECTION (2026-10-03, prototype-reusability-analysis)

**20130 is the DASHBOARD, not the API.** Verified empirically:

- `GET :20130/` → `307` redirect to `/dashboard` (Next.js SPA)
- `GET :20130/docs` → `200` but serves the web UI, not an OpenAPI spec
- `GET :20130/v1/models` → `401` (auth required)
- `GET :20130/v1/chat/completions` → `405` (route exists, wrong method)
- Omniroute `.env`: `API_PORT=20129`, `DASHBOARD_PORT=20128`,
  `PROD_API_PORT=20131`, `PROD_DASHBOARD_PORT=20130`

**Omniroute is OpenAI-API-compatible.** Source is local and open at
`/home/servidor/omniroute/`. Real contract (per
`omniroute/examples/quickstart/python_requests.py`):

```
POST /v1/chat/completions
Authorization: Bearer <api-key>
Content-Type: application/json
{"model": "Forsis", "stream": false, "messages": [...]}
```

The combo name goes directly in the `model` field — no prefix needed
(`src/lib/modelAliasResolver.ts` calls `getComboByName(model)`).

**Action for Phase 1:** target port **20129** (or 20131 for prod API), not
20130. `deployment-strategy.md`'s `OMNIROUTE_BASE_URL:
http://host.docker.internal:20130` needs correcting.

---

## CORRECTION #2 (2026-10-05, Phase 1 Agent 2) — SUPERSEDES THE ABOVE

**The port is 20130.** Both earlier versions of this file were wrong. The
correction above (pointing to 20129/20131) is **retracted**. Verified live
in this session with real HTTP calls — see `phase1/llm-provider.md` §1.

| Port | From host | From inside container | Verdict |
|---|---|---|---|
| 20128 | — | `ECONNREFUSED` | Do not use |
| 20129 | **no response** | 401 | Published by Docker but unreachable from host |
| **20130** | **`POST /v1/chat/completions` → 200 ✅** | 401 | **USE THIS** |
| 20131 | no response | **426 Upgrade Required** | It's a WebSocket (`EMBED_WS_PROXY_PORT`), NOT prod API |

Why Correction #1 was wrong: it read `# PROD_API_PORT=20131` from Omniroute's
`.env`, but **that line is commented out**. Port 20130 serves the Next.js
dashboard *and* the `/v1/*` API route handlers on the same port.

**Consequences:**
- `deployment-strategy.md` was **already correct** with 20130 — nothing to fix
  there. The "mandatory correction" in `PHASE-1-BRIEF.md` is void.
- `phase1/tools-design.md` (line 288) and its blocker **B-01** use 20129/20131
  and must be corrected to 20130. B-01 is now resolved.

**Combo confirmed:** `{"model":"Forsis"}` → 200. An unknown combo name returns
400 `"Unable to determine provider for model …"`, so the combo does exist.

**Three new findings (details in `phase1/llm-provider.md`):**
1. **JSON mode is NOT reliable** — `response_format:{"type":"json_object"}`
   yields parseable JSON only **70%** of the time (80% with fence-stripping).
   Omniroute accepts the field but does not validate or emulate it.
2. **The combo injects ~4,000 tokens** of its own system prompt per call
   (a bare `"ping"` reported `prompt_tokens: 4126`), and the responding model
   varies per call (claude-opus-5, gemini-3.8-flash, deepseek-v4, …). Pinning
   a specific model returns **402 Payment Required**.
3. **SECURITY:** `POST /v1/chat/completions` on `0.0.0.0:20130` returns **200
   with no `Authorization` header and with an invalid Bearer token**, while
   `GET /v1/models` correctly returns 401. Inference is effectively unauthenticated
   and network-reachable. Report to the Omniroute owner. Always send the
   Bearer header anyway, so the agent survives this being fixed.

**Measured latency (replaces the invalid Ollama benchmark):** p50 3.6s,
p95 10.5s, max 34.6s → proposed hard timeout **60s** per call, 120s per turn.
Note: Omniroute has a semantic cache (0.03s responses), so any future benchmark
must vary its inputs.

Reproducible scripts: `phase1/benchmarks/{bench.py,bench2.py}`

---
Generated: 2026-10-03 — Corrected: 2026-10-05
