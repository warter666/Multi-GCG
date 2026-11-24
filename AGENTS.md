# AGENTS.md

Conventions for working inside this repository. Scope: this directory only.

## What this is

Targeted tool-call attacks against tool-using LLM agents: GCG optimizes a document body so
the agent emits a privileged call it was never asked for. Multiple families, multi-hop
contexts. The design follows the public **Hybrid GCG** approach.

Purpose: mechanism validation on local fakes. **Not** a tool for attacking real systems.

## Method discipline (do not bypass to "make it run")

- The three gates in `legacy/gate.py` **must not be commented out** to get a run going:
  unchanged length, token-exact prefix, self-consistent target string. If a gate fails,
  fix `build_layout`; do not route around the check.
- Speedups are never evidence. Caches, approximations and sampling only shortlist candidates.
- Report failures by `failure_kind`, never as one aggregate success rate.
- **Runtime values must never be baked into the target.** The `exfil` `data` argument stays
  `{{RUNTIME_VALUE}}`; `--target-mode concrete` is a control experiment and must not appear
  in a conclusion.

- **A predicate hit is not a success.** Check the emitted call against the target
  (`--target-from`). CONFUSED_DEPUTY fires on any send the user did not ask for, including one
  the model started on its own initiative. Report the predicate and the target match
  separately.
- **State the filter policy with every number.** `--filter none` is an unguarded result. The
  guards are the point of the scenario: a payload that only works without them has proved
  nothing about a deployment.
- **A rate needs a denominator that varies the body.** Greedy decoding makes repeated runs of
  the same body identical, so "n runs" is not n samples. Count across search checkpoints,
  tasks and families, and name the conditions instead of quoting one percentage.
- **A missed hop 1 is not an optimization problem.** If the trace never reads the file the
  payload lives in, the search has nothing to do with the failure. Fix the task so the read is
  certain, then optimize the next hop. Check the trace's tool names before touching the recipe.
- **The harness must behave like an agent host.** The workspace listing, the typed argument
  schemas and one-dispatch-per-call are protocol, not decoration. Each of them was added after
  a trace showed the model inventing a path, inventing an argument name, or losing a call it
  did ask for. Fix those in the harness, never in the payload.

## Safety boundaries

- Run only against local fakes. No real mailbox, no outbound POST.
- The secret in the code is a placeholder (`sk-live-PLACEHOLDER-...`). Never swap in real data.
- Keep `http.post` URLs on unreachable domains such as `example.com`.
- Do not treat artifacts under `out/` as usable payloads; do not publish them.
- Model weights come from the HuggingFace cache; never commit tokens or local paths with
  credentials.

## Before touching anything

1. Run `python legacy/run.py --family deputy --model Qwen/Qwen2.5-0.5B-Instruct --dry-run`.
   It is the cheapest way to notice that the layout or the loss is wrong.
2. After editing `families.py`, run `--dry-run` for all four families.
3. L3 depends on an external predicate checker (`AICOMP_SDK_ROOT`). Changes that touch
   predicate semantics must stay aligned with it.

## Code conventions

- Python 3.11+, full type annotations, `from __future__ import annotations`.
- Comments explain **why**; identifiers say **what**.
- Do not add dependencies beyond transformers (accelerate is only for `device_map`).
- Memory-related constants belong in the CLI, not hardcoded in modules.- `torch` is imported inside functions so that judgement logic can be tested without a GPU.

## The old agent harness (`legacy/harness/`)

The harness exists so an attack is measured by what the agent actually does, not by a trace
we assembled ourselves. Rules:

- **Execution and judgement are separate.** `harness/loop.py` runs the loop and records
  events; it never decides whether an attack succeeded. Predicates are applied to the
  recorded trace afterwards (`verify.l3_on_trace`).
- **Never hand-build the trace.** `verify.synth_trace` is a shortcut for offline checks
  only. Any number reported as a result must come from a harness run.
- **Always run the control.** Treatment = poisoned document, control = clean document, same
  task, same seed. If the control already produces the target call, the "result" is the
  model's prior, not the adv. A treatment-only success is not a result.
- **Run the seed as a second baseline.** A hand-written instruction that already makes the
  agent emit the call (findings.md, Step 1) sets the bar. An adv that only matches the seed has
  proved nothing. An adv that scores worse than the seed has lost the instruction. Quote
  both numbers, from the same task and the same step budget.
- **Tools are local fakes.** In-memory files and mailbox, `http.post` recorded and never
  sent, `shell.run` recorded and never executed. No network, no real mailbox, no subprocess.
- **Only the intended page is poisoned.** `Env.poison_pages` decides which `web.open`
  targets return the payload; every other page is inert, so a control cannot leak it.
- **Deterministic.** Same messages + same seed -> same trace. No wall-clock, no randomness
  outside the seeded RNG.
- **Every step is accounted for.** A parse failure is an event with `ok: false`, not a
  silently skipped step. At most one retry, and the retry is counted. An unknown tool is
  recorded as `ok: false` with an error, never dropped.
- **The step budget is a parameter, not a vibe.** Stop at `--max-steps`; exhausting it is a
  measured outcome (`budget_exhausted`), not an exception.
- **One trace per episode**, one JSON object per event, frozen field set in
  `harness/trace.py`: `name, args, ok, output, side_effect, scope, source, error`.
  `source` is set by whichever tool produced the content (`web` / `email` / `file`), never
  by the attacker.  
- ONE FILE CAN ONLY WRITTEN DOWN BY ONE CODER AT THE SAME TIME, WHILE A REVIEWER MUST CHECK IT AFTER THE CODER FINISHED. HERE THE CODER AND THE REVIEWER ARE BOTH SUBAGENTS.
