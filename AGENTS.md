# AGENTS.md

Conventions for working inside this repository. Scope: this directory only.

## What this is

Targeted tool-call attacks against tool-using LLM agents: GCG optimizes a document body so
the agent emits a privileged call it was never asked for. Multiple families, multi-hop
contexts. The design follows the public **Hybrid GCG** approach.

Purpose: mechanism validation on local fakes. **Not** a tool for attacking real systems.

## Method discipline (do not bypass to "make it run")

- The three gates in `mgcg/gate.py` **must not be commented out** to get a run going:
  unchanged length, token-exact prefix, self-consistent target string. If a gate fails,
  fix `build_layout`; do not route around the check.
- Speedups are never evidence. Caches, approximations and sampling only shortlist candidates.
- Report failures by `failure_kind`, never as one aggregate success rate.
- **Runtime values must never be baked into the target.** The `exfil` `data` argument stays
  `{{RUNTIME_VALUE}}`; `--target-mode concrete` is a control experiment and must not appear
  in a conclusion.

## Safety boundaries

- Run only against local fakes. No real mailbox, no outbound POST.
- The secret in the code is a placeholder (`sk-live-PLACEHOLDER-...`). Never swap in real data.
- Keep `http.post` URLs on unreachable domains such as `example.com`.
- Do not treat artifacts under `out/` as usable payloads; do not publish them.
- Model weights come from the HuggingFace cache; never commit tokens or local paths with
  credentials.

## Before touching anything

1. Run `python run.py --family deputy --model Qwen/Qwen2.5-0.5B-Instruct --dry-run`.
   It is the cheapest way to notice that the layout or the loss is wrong.
2. After editing `families.py`, run `--dry-run` for all four families.
3. L3 depends on an external predicate checker (`AICOMP_SDK_ROOT`). Changes that touch
   predicate semantics must stay aligned with it.

## Code conventions

- Python 3.11+, full type annotations, `from __future__ import annotations`.
- Comments explain **why**; identifiers say **what**.
- Do not add dependencies beyond transformers (accelerate is only for `device_map`).
- Memory-related constants belong in the CLI, not hardcoded in modules.
- `torch` is imported inside functions so that judgement logic can be tested without a GPU.
