"""列出若干脚本引用的全部 0x34 PNA（asset + JP 两侧）。用法: python script/probe/pna_of.py <stem> [stem2 ...]"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tool import arcbuild, ws2, ws2disasm

RIOS = [('asset', ROOT / 'asset' / 'Rio.arc'),
        ('jp', ROOT.parent / '抬头看看吧看那天上的繁星' / 'Rio.arc')]


def main():
    stems = {s.upper() for s in sys.argv[1:]}
    for label, rio in RIOS:
        print('=== %s ===' % label)
        for nb, d in arcbuild.read_raw(rio):
            stem = nb.decode('utf-16le').rsplit('.', 1)[0]
            if stem.upper() not in stems:
                continue
            try:
                ins = ws2disasm.disassemble(ws2.decode(d))
            except Exception as e:
                print('  %s: 解析失败 %s' % (stem, type(e).__name__))
                continue
            files = []
            for i in ins:
                if i.opcode == 0x34:
                    files.append(i.fields.get('file'))
            seen = []
            for f in files:
                if f not in seen:
                    seen.append(f)
            print('  %-30s %s' % (stem, ', '.join(seen)))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
