# Features — Refinery Self-Discovery Demo

| # | Description | Date | Status |
|---|---|---|---|
| 1 | Self-discovery: elements self-register into the real bard-infra Registry | 2026-06-30 | Completed 2026-06-30 (Sprint 3; 116 elements verified active/stale/active live) |
| 2 | 5-section Baytown-modeled topology with realistic telemetry | 2026-06-30 | Completed 2026-06-30 (Sprint 1) |
| 3 | Bring-up sequence with hard interlock gates | 2026-06-30 | Completed 2026-06-30 (Sprint 4a) |
| 4 | Bring-down sequence (reverse, SIS-respecting) | 2026-06-30 | Completed 2026-06-30 (Sprint 4a) |
| 5 | Failure handling: fault injection + cascade propagation + SIS trip | 2026-06-30 | Completed 2026-06-30 (Sprint 4b) |
| 6 | Management console: 5-section schematic + live telemetry + controls | 2026-06-30 | Built 2026-06-30 (Sprint 6) — awaiting Eddie's visual sign-off |
| 9 | Console discovery panel wired to live Registry /agents (proxy) | 2026-06-30 | Open (follow-up; console currently single-origin to orchestrator) |
| 10 | Investigate tab — cascade/dependency graph view, trip propagation highlighted (restore cdn-sim Investigate) | 2026-06-30 | Open (console v2; Eddie 2026-06-30) |
| 11 | Authentic real-refinery DCS/ISA-101 HMI restyle (Linda research-informed; muted greys, alarm-reserved color, mimic view) | 2026-06-30 | Open (console v2; Eddie "model after a real refinery dashboard") |
| 12 | Time-series trend traces — multi-pen trends + per-tag sparklines (the strip-chart-recorder heritage) | 2026-06-30 | Open (console v2; Eddie "many visual traces over time") |
| 13 | Restore other cut cdn-sim chrome (tabs, alarm banner/ticker) where it applies | 2026-06-30 | Open (console v2) |
| 14 | Investigate tab: device "circle diagram" (sensors/valves/PLCs/switches/gateways/HMIs/servers) — two-architecture compare | 2026-06-30 | Open (Eddie 2026-06-30; see DESIGN_industrial_fabric.md) |
| 15 | Distributed fabric: per-device microcontroller + own control loop, self-discovery (built), cascade to industrial ARM gateways | 2026-06-30 | Open (the bard-infra hero design) |
| 16 | Shared Redis state store, replicated across separate areas → failover (faithful sim) | 2026-06-30 | Open |
| 17 | Digital twin: device's last-known state persists in the store and is shown when the device "dies" | 2026-06-30 | Open |
| 7 | Cloud Run demo-ready deployment | 2026-06-30 | Completed 2026-06-30 (Sprint 8; image built + run-verified; deploy is Eddie's to fire) |
| 8 | Per-element device identity (revocable) instead of shared fleet JWT | 2026-06-30 | Open (future; bard-infra device-enrollment exists) |
