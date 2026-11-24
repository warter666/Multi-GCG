# Research documents

This folder holds the long form of the project. The root `README.md` states the question, the
design, and the headline numbers. Everything below adds detail, and each file says what it is
for.

## Which document to read

| Document | Read it when you want | Contents |
| --- | --- | --- |
| `benchmark_spec.md` | The formal definition of the execution benchmark | Threat model, tasks, attacks, ground truth, metrics, trust levels |
| `stack_matrix.md` | All eight stacks on the same 36 cases | Verdict matrix, rates with intervals, margins, five results |
| `cross_model.md` | Whether the layer result survives another model | Three models, landed sets, parse failures, limits per model |
| `qwen05_diagnostics.md` | Where the parse failures come from | Token budget, failing shapes, event-level check |
| `procedures.md` | You want to run a specific experiment | One section per script, with flags |
| `results/case_set_matrix.md` | The raw `bench/` tables | Seven-column verdict table, Wilson intervals, margins |
| `results/experiments.md` | The per-cell rows behind sections 7.3 to 7.7 | Guard, write, and exfiltration cells |
| `findings.md` | The full research record | Traces, failures, the measurement bug, every table as measured |

The benchmark suites keep their own contracts:

| Document | Read it when you want | Contents |
| --- | --- | --- |
| `../bench/README.md` | To add or score a case in `bench/` | Schema, axes, seven verdicts, repetition rule |
| `../guardbench/README.md` | An overview of the paired suite | Layout, design notes, three configurations |
| `../guardbench/SPEC.md` | The execution contract of `guardbench/` | Protocol, metrics, evaluator, version block |
| `../guardbench/RESULTS_v0.3.md` | The full paired results | Metrics, intervals, paired movements, disagreements |

## Figures

All figures are hand-written SVG, one light and one dark copy. The README shows the current
theme through `#gh-light-mode-only` and `#gh-dark-mode-only`.

| Figure | Shows |
| --- | --- |
| `figures/pact_ladder_{light,dark}.svg` | Six texts against the judge, and the 0.5 threshold |
| `figures/l3_pairs_{light,dark}.svg` | Thirteen calls under `ship` and under `full` |
| `figures/ablation_{light,dark}.svg` | One mechanism removed at a time, 26 decisions |
| `figures/case_set_grid_{light,dark}.svg` | 36 cases against eight stacks |
| `figures/cross_model_{light,dark}.svg` | Three models, three stacks, with Wilson intervals |

## Reading paths

- A reviewer, five minutes: root `README.md`, then `stack_matrix.md` and
  `guardbench/RESULTS_v0.3.md`.
- A researcher who wants to reproduce: `procedures.md`, then `benchmark_spec.md`.
- A reader who wants the history: `findings.md`.

## File map

```
mgcg/model.py            Model loading
mgcg/runtime.py          One assistant turn: generate, parse a call, retry once
mgcg/deploy/             The scene: world, guards, episode, command line
mgcg/deploy/policy/      L3 as one layer: engine, request, canonical, encoded,
                         provenance, rules, decision, audit
mgcg/attacks/            The scoring surface on the judge, and CW
bench/cases.jsonl        The versioned execution case set: 36 cases
bench/policy_cases.jsonl Decisions for the internal ablation: 26 calls, no model
guardbench/cases.py      The paired case set: 34 cases, 15 pairs
guardbench/policy.py     The reference policy
guardbench/policy_engine.py  Adapter that runs mgcg.deploy.policy in the suite
scripts/bench_run.py     Runs every case on every stack, scores the traces; --rescore
scripts/bench_matrix.py  The eight-stack table from saved rows
scripts/bench_models.py  One table per model and stack, with parse-error columns
scripts/bench_diag.py    Parse sets, intersections and guard blocks from saved rows
scripts/bench_compare.py Two runs cell by cell
scripts/bench_attempt.py Attempt accounting from events
scripts/guardbench_report.py  Tables from finished guardbench rows
scripts/probe_judge.py   Judge reachability: controls and random suffixes
scripts/probe_clean.py   Normal mail against the judge: the false positive
scripts/probe_policy.py  Both policies on the same cases, side by side
scripts/l3policy.py      The shipped rules, asked directly, including writes
scripts/ablate_policy.py One mechanism removed at a time
scripts/probe_l3break.py Five ways to defeat the shipped rules
scripts/families.py      The write family and the token task, one model load
scripts/smoke_write.py   No-GPU check of the write channel and the task rule
scripts/matrix.sh        Five guard stacks against four payloads
legacy/                  The competition-era search, kept for one negative result
```

`legacy/` holds the competition-era search. It no longer names the project. It still matters for
two reasons: its negative result is cited in `findings.md`, and its proposal step is what
`mgcg/attacks/cw.py` reuses. GCG is one attacker here, not the method.
