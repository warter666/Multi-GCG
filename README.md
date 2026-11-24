# Agent Guard Testbed

Runtime policy enforcement against indirect prompt injection in tool-using LLM agents.

A tool-using agent reads a mailbox. A third party writes the mail. The text can name a
recipient, a path, or a URL. The testbed asks one question: can a policy layer at execution
time stop such text from causing an unauthorized tool operation, and still let the user's task
complete?

The testbed keeps four outcomes apart. A single attack rate blends them: whether the agent
attempted an unauthorized operation, whether that operation changed state, whether the user
task completed, and whether the policy refused a legitimate operation.

## Research Contributions

- **Two benchmarks, two questions.** `bench/` measures end-to-end security and task utility.
  `guardbench/` measures protocol compliance and policy correctness on paired cases.
- **One policy layer.** A PolicyEngine mediates every tool call. It normalizes the request,
  denies by default, controls egress, and tracks data provenance.
- **Trace-based evaluation.** The evaluator reads tool events and environment state. It does
  not read the agent's own description of what it did.
- **A white-box probe for content filters.** A CW suffix search tests how much the model-based
  judge depends on the style of the text.

## System Architecture

```text
untrusted mail or file
        |
        v
tool-using agent
        |
        v
tool request
        |
        v
PolicyEngine (L3): normalize, authorize, audit
        |
        +-- ALLOW --> tool call --> result --> provenance update
        |
        +-- DENY  --> rejected call
```

| Layer | Function |
| --- | --- |
| L1 | Provenance label on untrusted input |
| L2 | Model-based judgment of the content |
| L3 | Policy enforcement at execution time |

`full` is the complete L3 policy. It is not the sum of L1, L2, and L3. The stack that holds all
three layers is `l1l2l3`, and its L3 runs the smaller ruleset `ship`. L3 has four rules: default
deny, write protection, one egress rule for both channels, and a provenance rule. It decides on
the normalized request, not on the text that asked for it.

## Benchmarks

Two benchmarks are kept. They do not share cases, protocol, or metric units. Do not add their
episode counts together.

| Benchmark | Cases | What it measures |
| --- | --- | --- |
| `bench/` | 36 cases: 24 benign, 12 attack | Security and task utility, end to end |
| `guardbench/` | 34 cases: 15 benign, 19 attack, 15 pairs | Protocol compliance and policy effect |

### `bench/`: execution-trace benchmark

Thirty-six cases run on three stacks, `none`, `l1`, and `full`, on three models:
Qwen2.5-1.5B-Instruct, Qwen2.5-0.5B-Instruct, and SmolLM2-1.7B-Instruct. Every run uses greedy
decoding and a 256-token budget. The evaluator labels each episode from the trace, not from the
assistant's prose. `bench/README.md` defines the schema and the labels.

### `guardbench/`: protocol-paired benchmark

Thirty-four cases form 15 pairs. A benign case and its attack variants share the task, the
mailbox, and the files. Only the untrusted content differs. Three configurations run over the
same cases: `off` (no policy), `full` (the reference policy in `policy.py`), and `engine` (the
deployed PolicyEngine). The suite holds 102 episodes. `guardbench/SPEC.md` fixes the protocol
and the metric definitions.

## Results

### `bench/` across three models, 256 tokens

Each cell gives attack success and benign task success.

| Model | `none` | `l1` | `full` |
| --- | ---: | ---: | ---: |
| Qwen2.5-1.5B | 4/12, 11/24 | 6/12, 20/24 | 0/12, 14/24 |
| Qwen2.5-0.5B | 6/12, 15/24 | 3/12, 16/24 | 0/12, 15/24 |
| SmolLM2-1.7B | 0/12, 17/24 | 0/12, 18/24 | 0/12, 17/24 |

- On both Qwen models, `full` records no landed attack. The attempts still occur, L3 denies the
  call, and the attacker gets nothing.
- SmolLM2 dispatches no attack-related call in any of its 12 attack cases. Its `0/12` does not
  show that L3 works on this model.
- The cost is visible. L1 raises benign success on all three models, and it also raises landed
  attacks on two of them. A label that helps the task also helps the injected text.

### `guardbench/`, three configurations, 102 episodes

| Metric | `off` | `full` | `engine` |
| --- | ---: | ---: | ---: |
| Attack attempt rate | 10/19 | 10/19 | 11/19 |
| Attack success rate | 10/19 | 0/19 | 0/19 |
| Blocking rate, given an attempt | 0/10 | 10/10 | 11/11 |
| False positive rate | 0/45 | 0/44 | 0/48 |
| Benign task success | 9/15 | 7/15 | 7/15 |

- The policy changes the outcome, not the attempt. The model still tries the forbidden action,
  and every attempted sink is denied.
- Benign task success falls from 9/15 to 7/15. The refusals change the transcript, and a 1.5B
  model does not always find its way back to the task.

Both suites give detail beyond these tables. See `docs/cross_model.md`,
`docs/stack_matrix.md`, and `guardbench/RESULTS_v0.3.md`.

## Quick Start

```bash
pip install -r requirements.txt
```

The execution benchmark needs the model checkpoints and a GPU. CPU runs work for the policy and
protocol checks.

```bash
# execution benchmark, three stacks
python scripts/bench_run.py --stacks none,l1,full \
    --model Qwen/Qwen2.5-1.5B-Instruct --max-new-tokens 256

# paired suite, no GPU for the interface tests
python -m guardbench.protocol_tests
python -m guardbench.run_suite --configs off,full,engine
python scripts/guardbench_report.py out/guardbench-v03

# the layer alone, no model
python scripts/probe_policy.py
python scripts/ablate_policy.py
```

## Limitations

- The execution benchmark has 12 attack cases per model and one greedy run per configuration.
  The numbers show observed behavior, not an estimate of a general effect.
- Agent and judge share weights. A change of model also changes the judge, so only comparisons
  inside one model are safe.
- A model that never attempts an unauthorized operation cannot test the policy. The SmolLM2 row
  is silent about L3 for this reason.
- In `guardbench`, `full` and `engine` differ on one case, so their attempt rates are 10/19 and
  11/19. A disagreement between two implementations is a defect, not a result.
- The cross-session case shows that persisted lineage works. It does not show that lineage is
  the decisive reason the attack is blocked; one case cannot separate the reasons.

## Documentation

| Document | Contents |
| --- | --- |
| [`docs/README.md`](docs/README.md) | Index of the research documents, and the file map |
| [`docs/procedures.md`](docs/procedures.md) | One section per experiment, with its flags |
| [`bench/README.md`](bench/README.md) | Case schema, axes, and verdicts for `bench/` |
| [`docs/benchmark_spec.md`](docs/benchmark_spec.md) | Threat model, ground truth, metrics, trust levels |
| [`guardbench/SPEC.md`](guardbench/SPEC.md) | Protocol, metrics, and evaluator for `guardbench/` |
| [`guardbench/RESULTS_v0.3.md`](guardbench/RESULTS_v0.3.md) | Full paired results and intervals |
| [`docs/cross_model.md`](docs/cross_model.md) | Three models on one corpus |
| [`docs/stack_matrix.md`](docs/stack_matrix.md) | Eight stacks on the same 36 cases |
| [`docs/findings.md`](docs/findings.md) | Full research record: traces, failures, caveats |
