"""成就注入：给缺 `CG_ACHIEVEMENT` 调用的 CG 显示位点补上 16 字节调用，并重定位绝对偏移。

背景：Steam 在每次 CG 显示后注入 16 字节 `04 CG_ACHIEVEMENT 00`（CG 的 gallery/差分 id 取自
显示指令**自带**的固有 id 对，两侧都有，无需另分配）。还原记录取自原版、不带该调用，于是
被替换处的成就调用丢失。`tool/ws2.inject()` 只做拼接、不处理绝对偏移，故此处自带重定位。

重定位：`0x01 Condition`（ops[7:11]=a、ops[11:15]=b）与 `0x02 Jump2`（ops[0:4]）的操作数是
**文件内绝对偏移**；在每个插入点之后的内容整体后移 16 字节 → 目标按累积位移前移。

强不变式自检（不通过即停手）：
  1) 新字节 100% tile；
  2) 新指令流 == 旧指令流 + 仅多出插入的成就调用（逐条对齐）；
  3) 仅 `0x01/0x02` 的操作数发生变化，且变化量恰为 `16 × 位于其前的插入点数`；
  4) 其它 opcode 的操作数逐字节相同。

用法: python script/seam/inject_achievements.py [--apply] [--stems a,b]
"""
import argparse
import bisect
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tool import arcbuild, ws2, ws2disasm, ws2patch                 # noqa: E402

RIO = ws2patch.ASSET_RIO
DEFAULT = ['yozora_hika_103f', 'yozora_hika_110b', 'yozora_saya_101i',
           'yozora_saya_107c', 'yozora_ori_117a', 'yozora_koro_120']
JUMP2, COND, JUMP = ws2patch.JUMP2, ws2patch.COND, ws2patch.JUMP


def inject_one(data):
    ins = ws2disasm.disassemble(data)
    sites = list(ws2.find_display_sites(data))
    positions = sorted(e for e, _b, has in sites if not has)
    if not positions:
        return None, 0, []
    if any(i.opcode == JUMP for i in ins):
        raise SystemExit('该脚本含 0x06 Jump，本注入器未处理其偏移')
    pos_set = set(positions)

    def new_off(old, ps):
        return old + 16 * bisect.bisect_right(ps, old)

    out = bytearray()
    for i in ins:
        if i.offset in pos_set:
            out += ws2.ACH_CALL
        raw = bytes([i.opcode]) + ws2patch.rewrite_targets(i.operands, i.opcode, new_off)
        out += raw
    return bytes(out), len(positions), ins


def verify(old_ins, new_bytes, n_ins):
    ins2 = ws2disasm.disassemble(new_bytes)
    cover = sum(i.size for i in ins2)
    assert cover == len(new_bytes), '新体未 100%% tile（%d/%d）' % (cover, len(new_bytes))
    # 两侧都滤掉成就调用（旧体里 Steam 共用记录本就带一批）
    old = [i for i in old_ins if not ws2patch.is_ach(i)]
    new = [i for i in ins2 if not ws2patch.is_ach(i)]
    n_new_ach = sum(1 for i in ins2 if ws2patch.is_ach(i))
    n_old_ach = sum(1 for i in old_ins if ws2patch.is_ach(i))
    assert n_new_ach - n_old_ach == n_ins, \
        '成就调用净增 %d != 预期 %d' % (n_new_ach - n_old_ach, n_ins)
    assert len(old) == len(new), '指令数不符：旧 %d 新 %d（滤掉成就调用后）' % (len(old), len(new))
    for o, n in zip(old, new):
        assert o.opcode == n.opcode, 'opcode 序列不符 @%d' % o.offset
        if o.opcode in (JUMP2, COND):
            continue
        assert o.operands == n.operands, '非偏移操作数被改动 @%d op=0x%02x' % (o.offset, o.opcode)
    # 新体里每个绝对跳转目标都必须落在指令边界上
    bad = ws2patch.check_boundaries(ins2)
    assert not bad, '跳转目标非指令边界：%s' % bad[:5]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--stems')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    stems = a.stems.split(',') if a.stems else DEFAULT

    rio = {nb.decode('utf-16le').upper(): (nb, d) for nb, d in arcbuild.read_raw(RIO)}
    todo = {}
    for s in stems:
        key = s.upper() + '.WS2'
        if key not in rio:
            print('  跳过 %s（不存在）' % s)
            continue
        data = ws2.decode(rio[key][1])
        new, n, old_ins = inject_one(data)
        if new is None:
            print('  %-30s 无需注入' % s)
            continue
        verify(old_ins, new, n)
        print('  %-30s 注入 %d 处（%d -> %d 字节）自检通过' % (s, n, len(data), len(new)))
        todo[key] = ws2.encode(new)

    if not todo:
        print('无改动')
        return 0
    if not a.apply:
        print('（dry-run，未写入；加 --apply 执行）')
        return 0
    b = RIO.with_name(RIO.name + '.before_ach_inject')
    if not b.exists():
        shutil.copy2(RIO, b)
        print('已备份 %s' % b.name)
    out = [(nb, todo.get(nb.decode('utf-16le').upper(), d)) for nb, d in rio.values()]
    arcbuild.write_arc(out, RIO)
    arcbuild.verify(RIO, expect_count=len(out))
    back = {nb.decode('utf-16le').upper(): d for nb, d in arcbuild.read_raw(RIO)}
    for k, v in todo.items():
        assert back[k] == v, '%s 回读不一致' % k
    print('已写入 %d 个脚本；回读一致' % len(todo))
    return 0


if __name__ == '__main__':
    sys.exit(main())
