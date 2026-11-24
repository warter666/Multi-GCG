# Procedures

One section per experiment. Each section names the script, the flags, and what to read. The root
README keeps the two commands that a first run needs.

## 1. One episode

1. Make a payload file. The file holds the attacker text.
2. Run this command:

```
python -m mgcg.deploy.run --policy ship --payload-file out/pay-plain.txt --runs 1
```

3. Read the trace. Read the four axes.

Use `--layers l1,l2` to add the input guards. Use `--policy full` for the complete L3 layer.
Use `--policy none` and no layers for the control.

## 2. All guard stacks

1. Run `bash scripts/matrix.sh`.
2. The script makes four payloads and runs five stacks.

## 3. The judge

1. Run this command:

```
python scripts/probe_judge.py --vocab full --prefix-file out/pay-plain.txt --random 30
```

2. The script gives the verdict for five fixed control suffixes and for 30 random suffixes.
3. Run `python scripts/probe_clean.py`. It scores normal mail with no payload, so it measures
   the false positive directly. A control suffix cannot do that, because a suffix sits on top of
   the payload.

Do this before you report an attack rate. A random suffix shows what the judge does without an
attack.

## 4. The CW search

1. Run this command:

```
python -m mgcg.attacks.cw --vocab full --prefix-file out/pay-plain.txt --k 2.0 --restarts 8
```

2. The command prints one line per restart. It prints the smallest suffix that works.
3. Set `--vocab invisible` for the carrier test. The script then keeps only candidates that
   decode to invisible characters. The search fails. See `findings.md`.

## 5. The layer

1. Run `python scripts/l3policy.py` for the shipped rules.
2. Run `python scripts/probe_policy.py` for both policies on one page.
3. Run `python scripts/ablate_policy.py` for the internal ablation.

The three scripts ask the layer directly. They do not use a model. Use them when the model does
not chain two tool calls. See `findings.md`.

## 6. The write family and the token task

1. Run this command:

```
python scripts/families.py
```

2. The script loads the model once. It runs 14 cells: five write cells and nine token-task
   cells.
3. Use `--only T-mail` to run one group. The script prints a trace and a summary table.

## 7. The write channel without a GPU

1. Run `python scripts/smoke_write.py`.
2. The script checks the dispatcher, the D axis, both policy versions, and the task rule.
3. Every line must read PASS.

## 8. The case set

1. Run this command:

```
python scripts/bench_run.py --stacks none,l1,full
```

2. The runner reads `bench/cases.jsonl`: 36 cases, 24 benign and 12 attack, in eight families.
   Every case runs on every stack that you name.
3. Use `--only B-01,A-01` for a subset. Use `--limit 3` for a smoke run.
4. The runner writes `out/bench-<stamp>/results.jsonl`, one row per case and stack. A row holds
   the axes, the refusal reason, the parse failures, and the seconds spent.
5. The label comes from the trace: `landed`, `blocked`, `no-attempt`, `useful`, or `broken`.
   `bench/README.md` defines them. `stack_matrix.md` reports the result.

## 9. The eight-stack matrix

```
python scripts/bench_matrix.py out/bench-layer out/bench-matrix
```

A duplicate case-and-stack pair is checked for agreement. It is not merged.

## 10. The same corpus on other models

```
python scripts/bench_models.py --row qwen1.5=out/bench-qwen15-tok256 \
    --row qwen0.5=out/bench-qwen05-tok256-full --row smol1.7=out/bench-smol17-tok256-full
```

## 11. The paired suite

1. Run `python -m guardbench.protocol_tests`. This needs no GPU. All 14 tests must pass.
2. Run `python -m guardbench.run_suite --configs off,full,engine`.
3. Run `python scripts/guardbench_report.py out/guardbench-v03` to build the tables from the
   finished rows.

The suite writes one row per case and configuration. `guardbench/SPEC.md` fixes the protocol.
`guardbench/RESULTS_v0.3.md` holds the measured numbers.
