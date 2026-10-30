# Research record

The raw reverse-engineering trail behind the mod — kept as an archive of how each address and
mechanism was derived. These are working notes (dated, occasionally superseded by later
findings); the distilled, current explanation lives in [`../docs/ENGINEERING_LOG.md`](../docs/ENGINEERING_LOG.md)
and [`../docs/FUNCTION_MAP.md`](../docs/FUNCTION_MAP.md). Everything here is original analysis and
address/offset data (independent interoperability research) — no game code, assets, or keys.

| File | What |
|---|---|
| [HOOK_RESEARCH.md](HOOK_RESEARCH.md) | The initial scoping/plan: goal, the letsgo-recomp reference, the predicate fields, and the development plan — written before any Pikachu-1.0.2 patch existed. |
| [ORIGINAL_FINDINGS.md](ORIGINAL_FINDINGS.md) | First findings & handoff: the reward-path dead end, the predicate (`0x9D8A30`), the amount function's `+0x4A4` null-guard, and why clearing the instant-end flag is the real route. |
| [EXPERIMENT_LOG.md](EXPERIMENT_LOG.md) | The crash-isolation control matrix (EXP mod × tracer × party/follower × crash), which exonerated the environment and pointed at the addressing bug. |
| [INVESTIGATION_NOTES.md](INVESTIGATION_NOTES.md) | The post-faint crash (PoC C) investigation: ruling out the condvar theory, pinning the model-joint guard. |

See also [`../docs/WBEXP_STATIC_CALLGRAPH.md`](../docs/WBEXP_STATIC_CALLGRAPH.md) — the static
call-graph analysis of PWB's injection seam (the v0.4.1 encounter-exclusivity question).
