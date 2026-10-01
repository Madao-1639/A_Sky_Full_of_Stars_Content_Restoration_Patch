"""核查每个 CG 显示位点是否都带了 `CG_ACHIEVEMENT` 调用（成就注入的完整性）。

对 asset/Rio.arc 的**还原/接缝脚本**：用 `tool/ws2.find_display_sites()` 找出所有
`0x34 …PNA 0101 0b..01 0b..01` 位点，看紧后是否有 16 字节的 `04 CG_ACHIEVEMENT 00`。
缺失即表示该 CG 不会解锁成就（Steam 原本有、被还原记录替换后丢了）。

用法: python script/checks/check_achievements.py [--all]
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tool import arcbuild, resources, ws2                            # noqa: E402

RIO = ROOT / 'asset' / 'Rio.arc'
BAK = ROOT / 'backup' / 'Rio.arc'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--all', action='store_true', help='扫全部脚本（默认只扫 scenes.json 里的）')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    scenes = {s['id'].upper() + '.WS2' for s in resources.load('scenes.json')['scenes']}
    bak = {nb.decode('utf-16le').upper(): d for nb, d in arcbuild.read_raw(BAK)}
    bad = []
    for nb, d in arcbuild.read_raw(RIO):
        name = nb.decode('utf-16le')
        up = name.upper()
        if not up.endswith('.WS2'):
            continue
        if not a.all and up not in scenes:
            continue
        data = ws2.decode(d)
        sites = list(ws2.find_display_sites(data))
        miss = [(e, b) for e, b, has in sites if not has]
        # Steam 侧同名脚本的成就调用数（若有）
        se = up[:-4] + '_E.WS2'
        s_ach = None
        if se in bak:
            bd = ws2.decode(bak[se])
            s_ach = sum(1 for _e, _b, h in ws2.find_display_sites(bd) if h)
        n_ach = len(sites) - len(miss)
        flag = 'FAIL' if miss else 'OK '
        print('[%s] %-30s 位点 %2d 有调用 %2d 缺 %2d  (Steam 同名 %s)'
              % (flag, name, len(sites), n_ach, len(miss), s_ach))
        if miss:
            bad.append((name, [b for _e, b in miss]))
    print('\n缺失脚本 %d 个' % len(bad))
    for n, bs in bad:
        print('  %-30s 缺: %s' % (n, bs))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
