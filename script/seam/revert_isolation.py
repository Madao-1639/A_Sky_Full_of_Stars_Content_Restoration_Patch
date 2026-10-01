"""把指定脚本里的 `ORG_xxx` 引用改回裸名（误报隔离回退），并重定位绝对偏移。

背景：`--rejudge` 判定若干同名冲突为**误报**（Steam 版在被 `0x39` 选中的图层上与原版一致）
→ 应直接用 Steam 版（更高质量），撤掉隔离名。去 `ORG_` 每处 −4 字节 → 长度变化 →
`0x01 Condition`/`0x02 Jump2` 的**文件内绝对偏移**必须按累积位移重定位。

强不变式自检（不过就停手）：
  1) 新体 100% tile；
  2) 指令序列与旧体逐条同 opcode；除 `0x34`（改名）与 `0x01/0x02`（重定位）外，
     操作数逐字节相同；
  3) `0x01/0x02` 的新目标都落在指令边界上，且等于 `old + Σ(位于其前的改名位移)`。

用法: python script/seam/revert_isolation.py [--apply] [--scripts a,b] [--map ORG_X=bareX,...]
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tool import arcbuild, ws2, resources, ws2disasm, ws2patch        # noqa: E402

RIO = ws2patch.ASSET_RIO
GFX = ws2patch.GRAPHIC_RIO
DEC = ROOT / 'resource' / 'resource-decisions.json'


def default_plan():
    """[(script_stem, {org_name: bare_name})] —— 由 decisions 的「误报」+ 实际引用推出。"""
    dec = json.loads(DEC.read_text(encoding='utf-8'))
    rio = {nb.decode('utf-16le'): d for nb, d in arcbuild.read_raw(RIO)}
    orgs = [nb.decode('utf-16le') for nb, _d in arcbuild.read_raw(GFX)
            if nb.decode('utf-16le').upper().startswith('ORG_')]
    false_org = [o for o in orgs
                 if (dec.get(o[4:]) or {}).get('verdict') == '误报']
    by_script = {}
    for name, d in rio.items():
        if not name.upper().endswith('.WS2'):
            continue
        mp = {}
        for i in ws2disasm.disassemble(ws2.decode(d)):
            if i.opcode == 0x34:
                f = (i.fields.get('file') or '').upper()
                for o in false_org:
                    if f == o.upper():
                        mp[o] = o[4:]                     # 去 ORG_
        if mp:
            by_script[name] = mp
    return by_script, false_org


def splice(data, rmap):
    """rmap: {org_name: bare_name}（大小写不敏感匹配 0x34 的 file 字段）。"""
    ins = ws2disasm.disassemble(data)
    deltas = []                                            # (old_offset, delta)
    ops_per = {}
    for i in ins:
        if i.opcode != 0x34:
            continue
        f = (i.fields.get('file') or '')
        for org, bare in rmap.items():
            if f.upper() == org.upper():
                ob = org.encode('shift_jis')
                nb = bare.encode('shift_jis')
                raw_ops = i.operands
                # 在该指令的操作数里定位（大小写不敏感）并替换
                idx = raw_ops.upper().find(ob.upper())
                assert idx >= 0, '未在操作数里找到 %s' % org
                ops_per[i.offset] = (raw_ops[:idx] + nb + raw_ops[idx + len(ob):],
                                     nb, len(ob))
                deltas.append((i.offset, -4))
    if not deltas:
        return None, 0, ins
    deltas.sort()

    def new_off(x):
        return x + sum(d for p, d in deltas if p < x)

    out = bytearray()
    for i in ins:
        ops = ops_per[i.offset][0] if i.offset in ops_per else i.operands
        ops = ws2patch.rewrite_targets(ops, i.opcode, new_off)
        out += bytes([i.opcode]) + ops
    return bytes(out), len(deltas), ins


def verify(old_ins, new_bytes, renamed):
    ins2 = ws2disasm.disassemble(new_bytes)
    assert sum(i.size for i in ins2) == len(new_bytes), '新体未 100% tile'
    assert len(ins2) == len(old_ins), '指令数不符 %d vs %d' % (len(old_ins), len(ins2))
    for o, n in zip(old_ins, ins2):
        assert o.opcode == n.opcode, 'opcode 序列不符 @%d' % o.offset
        if o.opcode == 0x34:
            if o.offset in renamed:
                assert len(o.operands) - len(n.operands) == 4, '改名位点未恰好 -4 @%d' % o.offset
            else:
                assert o.operands == n.operands, '未改名位点被改动 @%d' % o.offset
        elif o.opcode in (0x01, 0x02):
            continue
        else:
            assert o.operands == n.operands, '非偏移操作数被改动 @%d' % o.offset
    bad = ws2patch.check_boundaries(ins2)
    assert not bad, '跳转目标非边界：%s' % bad[:5]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--drop', action='store_true', help='同时移除已无引用的隔离副本')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    by_script, false_org = default_plan()
    print('误报隔离副本 %d 个：%s' % (len(false_org), false_org))
    rio = {nb.decode('utf-16le').upper(): (nb, d) for nb, d in arcbuild.read_raw(RIO)}
    todo = {}
    for name, mp in sorted(by_script.items()):
        data = ws2.decode(rio[name.upper()][1])
        new, n, old_ins = splice(data, mp)
        if new is None:
            continue
        renamed = {i.offset for i in old_ins
                   if i.opcode == 0x34 and (i.fields.get('file') or '').upper()
                   in {o.upper() for o in mp}}
        verify(old_ins, new, renamed)
        print('  %-30s 改 %d 处（%d -> %d 字节）自检通过' % (name, n, len(data), len(new)))
        todo[name.upper()] = ws2.encode(new)

    if not todo:
        print('无需改动')
        return 0
    if not a.apply:
        print('（dry-run，未写入；加 --apply 执行）')
        return 0
    for p in (RIO, GFX):
        b = p.with_name(p.name + '.before_isolation_revert')
        if not b.exists():
            shutil.copy2(p, b)
            print('已备份 %s' % b.name)
    out = [(nb, todo.get(nb.decode('utf-16le').upper(), d)) for nb, d in rio.values()]
    arcbuild.write_arc(out, RIO)
    arcbuild.verify(RIO, expect_count=len(out))
    back = {nb.decode('utf-16le').upper(): d for nb, d in arcbuild.read_raw(RIO)}
    for k, v in todo.items():
        assert back[k] == v, '%s 回读不一致' % k
    print('Rio.arc 已写入 %d 个脚本' % len(todo))

    if a.drop:
        used = set()
        for nb, d in arcbuild.read_raw(RIO):
            if not nb.decode('utf-16le').upper().endswith('.WS2'):
                continue
            for i in ws2disasm.disassemble(ws2.decode(d)):
                if i.opcode == 0x34:
                    used.add((i.fields.get('file') or '').upper())
        gfx = [(nb, d) for nb, d in arcbuild.read_raw(GFX)]
        drop = {o.upper() for o in false_org} - used
        keep = [(nb, d) for nb, d in gfx if nb.decode('utf-16le').upper() not in drop]
        arcbuild.write_arc(keep, GFX)
        arcbuild.verify(GFX, expect_count=len(keep))
        print('Graphic.arc %d -> %d，移除 %s' % (len(gfx), len(keep), sorted(drop)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
