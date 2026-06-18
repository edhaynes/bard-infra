# ADR-0001: Single JSON envelope as the Router↔Agent wire protocol

Date: 2026-06-09
Status: Accepted (v1 — Crawl; contract frozen in `contracts/protocol.schema.json`, code in `common/protocol.py`)
Author: assistant draft; accepted by Eddie (2026-06-09 planning session)
Roadmap tier: v1 — Crawl (MVP)
Relates to: `DESIGN.md §3–§4`, `contracts/protocol.schema.json`, `contracts/router.openapi.yaml`, `contracts/agent.openapi.yaml`

## Context

Router, Talk Service, Agent, Registry, and the Flutter client all exchange the same
request/response shape. It is the single most-shared artifact, so it must be frozen before
parallel lanes build (DESIGN §4). The consumer app's existing OpenAI-compatible /
toolCalls–toolResults lineage is the natural basis.

## Decision

One JSON envelope for every hop:

- **Request:** `id`, `type` (`text`; `voice` reserved), `content`, `metadata{ targetAgent,
  sessionId, timestamp, authToken }`.
- **Response:** echoes `id`, may carry `toolCalls` / `toolResults`; errors use the structured
  shape `{ error, retry }` (e.g. `{error:"agent_unavailable", retry:true}`).

Frozen as `contracts/protocol.schema.json` (JSON Schema) and the OpenAPI files; modeled once
in `common/protocol.py` and imported, never re-defined per lane. A contract change is made in
`contracts/` and re-propagated — never patched in a lane (CLAUDE.md §14).

## Consequences

- Lanes test against fakes (`FakeRegistry`, `FakeAgent`) without importing each other.
- `metadata.authToken` validation lives behind a verifier interface (ADR-0006 / DESIGN §8h)
  so a PQ-identity verifier can replace JWT later without touching call sites.
- `voice` is wire-reserved now so the Talk Service can return `501` without a schema change
  when voice lands.

## Alternatives considered

- **gRPC / protobuf.** Better typing/perf, but heavier for an MVP and worse for the
  llama.cpp/OpenAI-compatible lineage and browser/console reuse. Revisit if throughput needs it.
- **Reuse the raw OpenAI schema directly.** Rejected: we need routing metadata
  (`targetAgent`, `authToken`) the OpenAI schema doesn't carry.
