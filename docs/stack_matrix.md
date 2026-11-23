# Stack matrix

Rows read: 288 across 8 stacks. Directories: out/bench-layer, out/bench-matrix.

No conflicting duplicates: every case and stack seen more than once agrees.

| stack | n_atk | attack_succeeded | safe_and_useful | blocked_but_failed | no_attempt_ok | no_attempt_failed | benign_success | benign_failure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| none | 12 | 4 | 0 | 0 | 4 | 4 | 11 | 13 |
| l1 | 12 | 6 | 0 | 0 | 5 | 1 | 19 | 5 |
| l2 | 12 | 1 | 0 | 8 | 2 | 1 | 9 | 15 |
| l3 | 12 | 0 | 2 | 5 | 4 | 1 | 12 | 12 |
| full | 12 | 0 | 2 | 5 | 4 | 1 | 12 | 12 |
| l1l2 | 12 | 2 | 8 | 0 | 1 | 1 | 19 | 5 |
| l1full | 12 | 0 | 2 | 4 | 5 | 1 | 19 | 5 |
| l1l2l3 | 12 | 1 | 8 | 1 | 1 | 1 | 19 | 5 |

## Rates

| stack | ASR | benign success | never attempted |
| --- | --- | --- | --- |
| none | 4/12 (0.14-0.61) | 11/24 (0.28-0.65) | 8/12 |
| l1 | 6/12 (0.25-0.75) | 19/24 (0.60-0.91) | 6/12 |
| l2 | 1/12 (0.01-0.35) | 9/24 (0.21-0.57) | 3/12 |
| l3 | 0/12 (0.00-0.24) | 12/24 (0.31-0.69) | 5/12 |
| full | 0/12 (0.00-0.24) | 12/24 (0.31-0.69) | 5/12 |
| l1l2 | 2/12 (0.05-0.45) | 19/24 (0.60-0.91) | 2/12 |
| l1full | 0/12 (0.00-0.24) | 19/24 (0.60-0.91) | 6/12 |
| l1l2l3 | 1/12 (0.01-0.35) | 19/24 (0.60-0.91) | 2/12 |

## Margins

| comparison | dASR | dBenign | dStopped_and_useful |
| --- | --- | --- | --- |
| l1 - none | +2 | +8 | +0 |
| l2 - none | -3 | -2 | +0 |
| l3 - none | -4 | +1 | +2 |
| full - none | -4 | +1 | +2 |
| l1l2 - none | -2 | +8 | +8 |
| l1l2l3 - l1l2 | -1 | +0 | +0 |
| l1full - l1 | -6 | +0 | +2 |
| full - l3 | +0 | +0 | +0 |
