# Case set: full verdict matrix, Qwen2.5-1.5B at 96 tokens

Eight stacks over 36 cases, all 288 episodes from `out/bench-layer` and `out/bench-matrix`.
Every cell is one episode, scored from the trace by `scripts/bench_matrix.py`. Attack counts
are out of twelve, benign counts out of twenty-four.

The summary figure and the five results are in
[README section 7.9](../../README.md#79-the-case-set-utility-and-attack-success-on-the-same-cases).

| Stack | attack_succeeded | safe_and_useful | blocked_but_failed | benign_success | benign_failure | no_attempt, task ok | no_attempt, task failed |
| --- | --- | --- | --- | --- | --- | --- | --- |
| none | 4/12 | 0/12 | 0/12 | 11/24 | 13/24 | 4/12 | 4/12 |
| l1 | 6/12 | 0/12 | 0/12 | 19/24 | 5/24 | 5/12 | 1/12 |
| l2 | 1/12 | 0/12 | 8/12 | 9/24 | 15/24 | 2/12 | 1/12 |
| l3 | 0/12 | 2/12 | 5/12 | 12/24 | 12/24 | 4/12 | 1/12 |
| full | 0/12 | 2/12 | 5/12 | 12/24 | 12/24 | 4/12 | 1/12 |
| l1l2 | 2/12 | 8/12 | 0/12 | 19/24 | 5/24 | 1/12 | 1/12 |
| l1full | 0/12 | 2/12 | 4/12 | 19/24 | 5/24 | 5/12 | 1/12 |
| l1l2l3 | 1/12 | 8/12 | 1/12 | 19/24 | 5/24 | 1/12 | 1/12 |

ASR and benign success with Wilson 95% intervals:

| Stack | ASR | benign success | never attempted |
| --- | --- | --- | --- |
| none | 4/12 (0.14-0.61) | 11/24 (0.28-0.65) | 8/12 |
| l1 | 6/12 (0.25-0.75) | 19/24 (0.60-0.91) | 6/12 |
| l2 | 1/12 (0.01-0.35) | 9/24 (0.21-0.57) | 3/12 |
| l3 | 0/12 (0.00-0.24) | 12/24 (0.31-0.69) | 5/12 |
| full | 0/12 (0.00-0.24) | 12/24 (0.31-0.69) | 5/12 |
| l1l2 | 2/12 (0.05-0.45) | 19/24 (0.60-0.91) | 2/12 |
| l1full | 0/12 (0.00-0.24) | 19/24 (0.60-0.91) | 6/12 |
| l1l2l3 | 1/12 (0.01-0.35) | 19/24 (0.60-0.91) | 2/12 |

Margins, paired by case (descriptive differences, not estimates of a general effect):

| Comparison | change in landed attacks | change in benign success | change in safe_and_useful |
| --- | --- | --- | --- |
| `l1` - `none` | +2 | +8 | 0 |
| `l2` - `none` | -3 | -2 | 0 |
| `l3` - `none` | -4 | +1 | +2 |
| `l1l2` - `none` | -2 | +8 | +8 |
| `l1l2l3` - `l1l2` | -1 | 0 | 0 |
| `l1full` - `l1` | -6 | 0 | +2 |
| `full` - `l3` | 0 | 0 | 0 |
