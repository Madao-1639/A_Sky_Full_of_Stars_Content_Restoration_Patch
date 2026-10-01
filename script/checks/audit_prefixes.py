"""盘点每个场景的 `0x15` 说话人前缀，分类为：日文名（有日→中映射）/ 英文键 / 其它。

规范口径（用户 2026-09-17）：**照搬自日文原版的脚本，前缀应当用日文名**（走 NameTable 的
日文名→中文映射）；出现英文键前缀即为不规范，应统一成日文名。

用法: python script/checks/audit_prefixes.py [--kind H,bare,seam]
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
from tool import arcbuild, resources, ws2, ws2disasm                # noqa: E402
from script.seam import mk_nametable as NT                                          # noqa: E402

RIO = ROOT / 'asset' / 'Rio.arc'
ZH = ROOT / 'asset' / 'zh-CN' / 'Rio.arc'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--kind')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    scenes = resources.load('scenes.json')['scenes']
    if a.kind:
        kinds = set(a.kind.split(','))
        scenes = [s for s in scenes if s.get('kind') in kinds]
    zh = {nb.decode('utf-16le'): d for nb, d in arcbuild.read_raw(ZH)}
    nt = zh['NameTable.txt'].decode('utf-16le')
    en_keys = {ln.split('\t')[0] for ln in nt.split('\r\n') if '\t' in ln}
    rio = {nb.decode('utf-16le').lower(): d for nb, d in arcbuild.read_raw(RIO)}
    jp2cn = dict(NT.JP2CN)
    jp2cn.update({'%LF' + k: v for k, v in NT.JP2CN.items()})

    rows = []
    for s in scenes:
        stem = s['id'].lower() + '.ws2'
        if stem not in rio:
            continue
        prefs = set()
        for i in ws2disasm.disassemble(ws2.decode(rio[stem])):
            if i.opcode == 0x15:
                p = i.fields.get('prefix') or ''
                if p:
                    prefs.add(p)
        jp = sorted(p for p in prefs if p in jp2cn or p.startswith('%LF') and p[3:] in NT.JP2EN)
        en = sorted(p for p in prefs if p in en_keys and p not in jp)
        other = sorted(p for p in prefs if p not in jp and p not in en)
        rows.append((s['id'], s.get('kind'), jp, en, other))

    print('%-28s %-6s %s' % ('场景', 'kind', '前缀分类（日文 / 英文 / 其它）'))
    n_bad = 0
    for sid, kind, jp, en, other in rows:
        flag = '  ← 不规范' if (en or other) else ''
        if en or other:
            n_bad += 1
        print('%-28s %-6s 日文 %s | 英文 %s | 其它 %s%s'
              % (sid, kind, jp or '—', en or '—', other or '—', flag))
    print('\n不规范场景 %d 个' % n_bad)


if __name__ == '__main__':
    main()
