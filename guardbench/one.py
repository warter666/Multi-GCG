import sys
sys.path.insert(0, '/home/tbtb/projects/multi-gcg')
from guardbench import cases, runner, evaluate

cid = sys.argv[1] if len(sys.argv) > 1 else 'S2_benign'
cfg = sys.argv[2] if len(sys.argv) > 2 else 'off'
case = [c for c in cases.all_cases() if c['id'] == cid][0]
tok, model = runner.load()
run = runner.run_case(case, None, tok, model, config=cfg)
row = evaluate.score(case, run)
print('case', cid, cfg, 'utility', row['utility_ok'], 'missing', row['required_missing'])
print('protocol', row['protocol'])
for e in run['events']:
    if e['kind'] == 'protocol_error':
        print('PROTO', e['step'], e['code'], '|', e.get('text', '')[:140].replace('\n', ' '))
    else:
        print('CALL ', e['step'], e['tool'], e['args'], '->', e['blocked_by'], e['error'])
print('reads', run['state']['email_reads'], run['state']['file_reads'])
for s in run['state']['sent']:
    print('SENT to', s['to'], '|', s['subject'], '|', s['body'][:100].replace('\n', ' '))
