Status: In Progress
Author: Jason-infra
Started: 2026-07-02

# PLAN — vLLM LLM-router plugin (owner-enabled inference resource)

The first **owner-enabled resource** of ADR-0018: an LLM the owner turns on for a
capable device/workgroup. Served by **vLLM**, OpenAI-compatible. Two tiers —
a **little model up fast** for instant answers, a **big model warming in the
background**; requests route to whichever tier is ready. (Eddie 2026-07-02:
"start with the little server, have big llm build in the background.")

## Decisions (Eddie, 2026-07-02)
- **Engine = vLLM** ("vllm would be cool cause it has little llms itself").
- **Target = gx10** (GB10, aarch64). Eddie has run vLLM on ARM before, so the
  ARM caveat is discharged — the community GB10 images (sm_121 + CUDA 13) work.
- **Two tiers, little-first:** little model answers immediately; big model loads
  in the background; the router prefers big once healthy, else little.
- **Offer both** little + big models via config.

## Why this is small
vLLM is **OpenAI-compatible**, and the agent's `LlamaCppEngine` is already a
generic OpenAI-compatible forwarder (`/v1/chat/completions`). So the agent side
is a **config alias**, not new inference code. The plugin is a manifest + a
deploy recipe.

## Landed (this scaffold — green, 100% cov, 669 tests)
- `examples/plugins/vllm-router.manifest.json` — the plugin (`kind: service`,
  `entry: container`, `requiredCapabilities: ["gpu","llm"]` so it's only offered
  on capable nodes, `healthEndpoint: /health`, configSchema = littleModel /
  bigModel / port / maxModelLen / gpuMemoryUtilization / dtype / modelCacheDir).
- `agent/engine.py` — `vllm` backend (reuses the OpenAI-compatible engine, wired
  from `vllm_*` config; `backend_label` makes errors name vLLM). `common/config.py`
  — `vllm_base_url` / `vllm_model` / `vllm_api_key`.
- `scripts/run_vllm_gx10.sh` — the gx10 bring-up recipe: **storage forced to
  `/srv/models`** (root fs is 99% full — hard constraint), GPU via the host CDI
  spec, little tier now + big tier warming, waits on `/health`.

## Blocked on Eddie (deployment step)
- **Which GB10 vLLM image?** Asked; awaiting his known-good ref (he's run it on
  ARM before). Default in the manifest/script is the community
  `hellohal2064/vllm-dgx-spark-gb10` — SWAP for his.
- Then: run `scripts/run_vllm_gx10.sh` on gx10 → verify little `/health` + a
  completion → confirm big model warms → point an agent's `vllm` backend at it.

## Remaining after deploy
- **The router tier-picker** (little↔big): MVP = the little server is the
  endpoint; add a thin OpenAI-compatible front that prefers big once `/health`
  passes, else little. Evaluate LiteLLM (routing/fallback) vs a small proxy vs
  the fabric Router.
- Wire the plugin into the console Plugins pane (enable per device/workgroup) —
  the manifest is already catalog-loadable.
- Model weights: HF-format on `/srv/models/hf`. (Ollama GGUFs on gx10 are a
  different format — a Vulcan-on-vLLM path needs converted weights.)
