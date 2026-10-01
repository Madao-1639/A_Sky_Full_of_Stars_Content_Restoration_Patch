"""核查 asset/Rio.arc 全部脚本用到的 `%LF` 说话人前缀是否都命中 NameTable.txt。

用法: python script/checks/check_nametable.py [--only-restored]
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tool import arcbuild, resources, ws2, ws2disasm                    # noqa: E402

RIO = ROOT / 'asset' / 'Rio.arc'
ZH = ROOT / 'asset' / 'zh-CN' / 'Rio.arc'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only-restored', action='store_true')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    scenes = {s['id'].upper() + '.WS2' for s in resources.load('scenes.json')['scenes']}
    zh = {nb.decode('utf-16le'): d for nb, d in arcbuild.read_raw(ZH)}
    keys = {ln.split('\t')[0] for ln in zh['NameTable.txt'].decode('utf-16le').split('\r\n')
            if '\t' in ln}
    # 故意不入表的**恒等前缀**：引擎查不到键时原样显示名字（依据：日文原版构建根本没有
    # NameTable.txt 也照常显示），故 `%LF沙夜`→`沙夜`、`%LF武一`→`武一` 这类键==值的映射冗余、
    # 已从表中删除（见 script/checks/prune_nametable.py --identity）。
    RAW_OK = {'%LF沙夜', '%LF武一'}
    miss = defaultdict(set)
    for nb, d in arcbuild.read_raw(RIO):
        name = nb.decode('utf-16le')
        if not name.upper().endswith('.WS2'):
            continue
        if a.only_restored and name.upper() not in scenes:
            continue
        try:
            ins = ws2disasm.disassemble(ws2.decode(d))
        except Exception:
            continue
        for i in ins:
            if i.opcode == 0x15:
                p = i.fields.get('prefix') or ''
                if p.startswith('%LF') and p not in keys and p not in RAW_OK:
                    miss[p].add(name)
    print('NameTable 键 %d 条' % len(keys))
    if not miss:
        print('OK 所有前缀均命中')
        return 0
    print('未命中 %d 种：' % len(miss))
    for p, sc in sorted(miss.items()):
        print('  %-24s 用于 %s' % (p, sorted(sc)[:4]))
    return 1


if __name__ == '__main__':
    sys.exit(main())
