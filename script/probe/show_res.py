"""查 `resource/resource-decisions.json` 里匹配关键字的条目（同名冲突的最终取舍）。

用法: python script/probe/show_res.py CUTIN KOR_04
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[2]
dec = json.loads((ROOT / 'resource' / 'resource-decisions.json').read_text(encoding='utf-8'))
kws = [a.upper() for a in sys.argv[1:]]
if not kws:
    raise SystemExit(__doc__)
for name, v in sorted(dec.items()):
    if name.startswith('_') or not any(k in name.upper() for k in kws):
        continue
    print('%-24s %-8s iso=%s' % (name, v.get('verdict') or '—', v.get('isolation_name') or '—'))
