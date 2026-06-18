# ADR-0003: UBI + Podman agent running llama.cpp inference

Date: 2026-06-09
Status: Accepted (v1 — Crawl; Containerfile exists, llama.cpp engine lands Sprint 1)
Author: assistant draft; accepted by Eddie (2026-06-09 planning session)
Roadmap tier: v1 — Crawl (MVP)
Relates to: `DESIGN.md §3 / §6 Lane C`, `agent/`, `contracts/agent.openapi.yaml`, `contracts/power-profile.schema.yaml`, `docs/MEMORY.md` (UBI runtime)

## Context

The agent is the unit that actually serves a model. It must be portable (multi-arch),
sandboxed, resource-capped, and self-contained for an on-prem Pro story. The consumer app's
inference lineage is **llama.cpp**, and the MVP decision (ROADMAP) is to run a real model in
the agent rather than depend on an external endpoint.

## Decision

- **Image:** `FROM registry.access.redhat.com/ubi…` — **UBI 10 by default, UBI 9 where a
  package or the RHEL 10 x86-64-v3 baseline forces it** (`docs/MEMORY.md`). The existing
  `agent/Containerfile` is UBI-9; migration to UBI-10 is a tracked follow-up.
- **Inference:** a `LlamaCppEngine` implements the `InferenceEngine` protocol and fronts a
  llama.cpp OpenAI-compatible server; **LiteLLM** routes to it. The `EchoEngine` stub is
  retained only for tests/fakes. ("Athena"/vLLM is a *backend reachable through LiteLLM*, not
  a second router — see ADR-0001 and the corrected source docs.)
- **HTTP:** `POST /infer`, `/healthz` per `contracts/agent.openapi.yaml`.
- **Resources:** entrypoint honours `--cpus` / `--memory` / `--pids-limit` (and optional
  `--gpus all`) derived from `power-profile.schema.yaml`.
- **HW accel (MVP):** NVIDIA on Linux via the NVIDIA Container Toolkit only.
- **Multi-arch:** `podman buildx` builds `linux/amd64` + `linux/arm64`.

## Consequences

- The agent is self-contained: pull image + a GGUF (config-driven fetch) and it serves a
  model on any supported host — no external model dependency.
- Model bundling size and the arm64 llama.cpp build are the main Sprint 1 risks; Sprint 1 is
  split 1a/1b/1c to de-risk (ROADMAP / CLAUDE.md §17).
- iOS cannot run this container (no Linux kernel/namespaces); iOS is a **client only** and
  reaches an agent remotely (v2) or runs a native on-device endpoint later.

## Alternatives considered

- **LiteLLM → external OpenAI/vLLM endpoint** (no local model). Faster to a "real" answer but
  makes the MVP depend on an externally-hosted model — rejected for the on-prem Pro story.
- **vLLM as the in-agent server.** Heavier; better for datacenter NVIDIA later. llama.cpp fits
  the lineage and the broad-hardware MVP. vLLM remains a v2+ backend behind LiteLLM.
- **Docker base image.** Rejected per standing decision: Red Hat UBI + Podman first
  (`docs/MEMORY.md`).
