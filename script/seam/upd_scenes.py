"""把已重建的接缝脚本登记进 resource/scenes.json（kind = "seam"）。

只登记 asset/Rio.arc 里**确实存在**的新脚本；已登记的不重复。
用法: python script/seam/upd_scenes.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tool import arcbuild                                        # noqa: E402

SCENES = ROOT / 'resource' / 'scenes.json'
SEAM = ROOT / 'resource' / 'seam-diffs.json'


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    have = {nb.decode('utf-16le').rsplit('.', 1)[0].lower()
            for nb, _d in arcbuild.read_raw(ROOT / 'asset' / 'Rio.arc')}
    table = json.loads(SCENES.read_text(encoding='utf-8'))
    known = {s['id'] for s in table['scenes']}
    scripts = [s for s in json.loads(SEAM.read_text(encoding='utf-8'))['scripts']]
    add = []
    for s in scripts:
        stem = s['orig'].lower()
        if stem in known or stem not in have:
            continue
        route = s['steam'].split('_')[1]
        add.append({'id': stem, 'route': route, 'kind': 'seam'})
    if not add:
        print('无新增（已是最新）')
        return
    table['scenes'] += add
    SCENES.write_text(json.dumps(table, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('已登记 %d 个接缝脚本：' % len(add))
    for x in add:
        print('   %-26s %s' % (x['id'], x['route']))


if __name__ == '__main__':
    main()
