"""列出"被旁路脚本"的删除候选并做安全检查（只读，除非 --apply）。

候选：
  1. 每个 `kind == "seam"` 场景对应的 Steam 原脚本 `<id>_E.ws2`（已被去 `_E` 的重建脚本取代）
  2. 3 个 Steam 过审 H 场景孤儿：`yozora_hika_103d_H_E` / `yozora_hika_110c_H_E` / `yozora_saya_101j_H_E`
  3. 上述各脚本在 `asset/zh-CN/Rio.arc` 的同名 `.lng`

安全检查：全脚本里**不得**再有 `0x04/0x07` 指向任一候选；否则停手。
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tool import arcbuild, ws2, resources, ws2patch                  # noqa: E402

RIO = ws2patch.ASSET_RIO
ZH = ws2patch.ZH_RIO
BACKUP_RIO = ws2patch.BACKUP_RIO
SCENES = ROOT / 'resource' / 'scenes.json'
OUT_TABLE = ROOT / 'resource' / 'removed-scripts.json'
H_E = ['yozora_hika_103d_H_E', 'yozora_hika_110c_H_E', 'yozora_saya_101j_H_E']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')

    scenes = resources.load('scenes.json')['scenes']
    cand = sorted({s['id'] + '_E' for s in scenes if s.get('kind') == 'seam'} | set(H_E))

    rio = {nb.decode('utf-16le').upper(): (nb, d) for nb, d in arcbuild.read_raw(RIO)}
    zh = {nb.decode('utf-16le').upper(): (nb, d) for nb, d in arcbuild.read_raw(ZH)}
    bak_names = {nb.decode('utf-16le').upper() for nb, _d in arcbuild.read_raw(BACKUP_RIO)}
    drop_set = {c.upper() + '.WS2' for c in cand}

    # 全脚本引用扫描（0x04 RunFile / 0x07 NextFile 后接 NUL 结尾的大写名）；
    # 来源脚本若自身也在待删集合里，忽略（自相引用）
    dec = {name: ws2.decode(d) for name, (nb, d) in rio.items()
           if name.endswith('.WS2') and name not in drop_set}
    rev = ws2patch.call_graph(dec)
    refs = {t: rev[t] for t in drop_set if rev.get(t)}

    print('候选 %d 个：' % len(cand))
    rem_rio, rem_zh = [], []
    for c in cand:
        up = c.upper() + '.WS2'
        in_rio = up in rio
        in_bak = up in bak_names
        lng = (c + '.lng').upper()
        in_zh = lng in zh
        r = sorted(refs.get(up, []))
        print('  %-26s asset=%s backup=%s .lng=%s  被引用=%s'
              % (c, in_rio, in_bak, in_zh, r or '无'))
        if in_rio:
            rem_rio.append(c)
        if in_zh:
            rem_zh.append(c + '.lng')

    blocked = {k: sorted(v) for k, v in refs.items()}
    if blocked:
        print('\n!! 仍有引用，停手：%s' % blocked)
        return 1
    print('\n将删除：Rio.arc %d 个、zh-CN/Rio.arc %d 个' % (len(rem_rio), len(rem_zh)))

    if not a.apply:
        print('（dry-run，未写入；加 --apply 执行）')
        return 0

    for p in (RIO, ZH):
        b = p.with_name(p.name + '.before_removal')
        if not b.exists():
            shutil.copy2(p, b)
            print('已备份 %s' % b.name)

    drop_rio = {c.upper() + '.WS2' for c in rem_rio}
    out_rio = [(nb, d) for nb, d in rio.values() if nb.decode('utf-16le').upper() not in drop_rio]
    arcbuild.write_arc(out_rio, RIO)
    arcbuild.verify(RIO, expect_count=len(out_rio))
    drop_zh = {ln.upper() for ln in rem_zh}
    out_zh = [(nb, d) for nb, d in zh.values() if nb.decode('utf-16le').upper() not in drop_zh]
    arcbuild.write_arc(out_zh, ZH)
    arcbuild.verify(ZH, expect_count=len(out_zh))

    back = {nb.decode('utf-16le').upper() for nb, _d in arcbuild.read_raw(RIO)}
    assert not (drop_rio & back), '回读仍存在'
    backz = {nb.decode('utf-16le').upper() for nb, _d in arcbuild.read_raw(ZH)}
    assert not (drop_zh & backz), '回读仍存在'
    print('Rio.arc %d -> %d；zh-CN/Rio.arc %d -> %d'
          % (len(rio), len(out_rio), len(zh), len(out_zh)))

    OUT_TABLE.write_text(json.dumps({
        '_comment': ('有意删除的 Steam 成员（补丁"零破坏性"检查的例外白名单）。'
                     '理由：被旁路的 Steam `*_E` 脚本已由去掉 `_E` 的重建接缝脚本取代；'
                     '3 个 `*_H_E` 是 Steam 过审 H 场景的孤儿替换版。删除前已确认全脚本无 '
                     '`0x04/0x07` 指向它们。备份：Rio.arc/Rio.arc.before_removal、'
                     'zh-CN/Rio.arc.before_removal。'),
        'rio': sorted(drop_rio), 'zh': sorted(drop_zh),
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('已写出 %s' % OUT_TABLE)
    return 0


if __name__ == '__main__':
    sys.exit(main())
