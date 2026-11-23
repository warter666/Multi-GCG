# guardbench

A paired, state-scored benchmark for a unified policy layer in a tool-calling agent.
Version 0.3: 34 cases, 15 pairs, three configurations, 102 episodes.

    python -m guardbench.protocol_tests                        # interface contract, no GPU
    python -m guardbench.run_suite --configs off,full,engine    # the paired suite
    python scripts/guardbench_report.py out/guardbench-v03      # tables from finished rows

Read `SPEC.md` first. It fixes what is measured, the execution contract, and what may not be
changed without bumping the version. Numbers live in `RESULTS_v0.3.md`, and the rows behind
them in `results/v0.3/`.

`off` runs with no policy, `full` with the reference implementation in `policy.py`, and
`engine` with the shipped `mgcg.deploy.policy` layer through an adapter. The last two are two
implementations of the same claim: a case where they disagree is a bug in one of them, not a
result.

## Layout

| file | role |
| --- | --- |
| `scene.py` | world constants, address/host normalization, decoding-tolerant value matching |
| `iface.py` | the one-action contract: parse, validate, refuse; no silent repair |
| `policy.py` | reference L3: allowlist, protected paths, taint, lineage |
| `policy_engine.py` | adapter that runs the shipped `mgcg.deploy.policy` layer in this suite |
| `cases.py` | 34 cases: 15 benign, 19 attack, in 15 pairs |
| `runner.py` | one episode, or two sessions when the case declares it |
| `evaluate.py` | state assertions, required vs forbidden, baseline noise |
| `metrics.py` | PCR, TSR, attempt rate, ASR, blocking rate, FPR, noise |
| `run_suite.py` | run every case under every policy config, print and save |
| `protocol_tests.py` | 14 scripted interface tests |

## Design notes

Cases are paired. A benign case and its attack variants share the task, the mailbox and the
files; only the untrusted content differs. Comparing unrelated benign and attack prompts
cannot tell you whether a blocked action was the injection or the model's own invention.

The interface is strict on purpose. One action per turn, nothing repaired, one retry. A model
that batches calls is measured as a model that batches calls, not as a model that was
attacked.

Protocol errors, preconditions, policy denials and attack side effects are four different
columns. Collapsing any two of them produces a number that reads better than it is.

Because decoding is greedy, repeating a case reproduces the same trajectory. Variation must
come from new cases or new attack variants, not from reruns. The suite therefore reports a
single deterministic run per case, and the second attack variant on a pair is what stands in
for sampling.

A two-session case keeps the workspace and throws away the process: the second session is a
fresh context and a fresh policy instance. Only what the policy persisted to disk can carry
over, which is the property the lineage store exists for.
