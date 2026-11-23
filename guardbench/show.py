import json, sys
p = sys.argv[1]
for line in open(p):
    r = json.loads(line)
    print('%-11s %-4s u=%d miss=%s att=%d exe=%d recon=%d un=%s prot=%d/%d retry=%d'
          % (r['case'], r['config'], r['utility_ok'], r['required_missing'],
             r['attack_attempted'], r['attack_executed'], r.get('attack_recon', -1),
             ','.join(r['unintended']) or '-', r['protocol']['valid'],
             r['protocol']['invalid'], r['protocol']['retries']))
