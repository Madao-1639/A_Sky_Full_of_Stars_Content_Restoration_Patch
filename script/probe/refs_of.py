"""列出资源被哪些脚本引用（同时扫 asset/ 与日文原版，给出脚本名以便判顺序）。

用法: python script/probe/refs_of.py <names-file>
"""
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tool import arcbuild, ws2, ws2disasm

ASSET_RIO = ROOT / 'asset' / 'Rio.arc'
JP_RIO = ROOT.parent / '抬头看看吧看那天上的繁星' / 'Rio.arc'


def scan(rio, want):
    out = defaultdict(lambda: defaultdict(set))
    for nb, d in arcbuild.read_raw(rio):
        stem = nb.decode('utf-16le').rsplit('.', 1)[0]
        try:
            ins = ws2disasm.disassemble(ws2.decode(d))
        except Exception:
            continue
        for i in ins:
            if i.opcode != 0x34:
                continue
            k = (i.fields.get('file') or '').upper()
            if k in want:
                out[k][i.fields.get('file')].add(stem)
    return out


def main():
    names = [ln.strip() for ln in Path(sys.argv[1]).read_text(encoding='utf-8').splitlines()
             if ln.strip() and not ln.startswith('#')]
    want = {n.upper(): n for n in names}
    for label, rio in (('asset (补丁)', ASSET_RIO), ('原版 (JP)', JP_RIO)):
        print('=== %s ===' % label)
        res = scan(rio, want)
        for n in names:
            ku = n.upper()
            if ku not in res:
                continue
            for form, scripts in sorted(res[ku].items()):
                print('  %-18s %-20s %s' % (n, form, ', '.join(sorted(scripts))))
        print()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
