"""把被替换 Steam 脚本里的 `0xf0 <成就 id>` 成就调用补回替代脚本（与 0x0b 解锁位点同一类缺陷）。

背景（doc/file-formats.md「`0xf0`：Steam 成就解锁调用」）：
`0xf0 <u8>` 是 **Steam 成就解锁**调用（本作 20 个成就，id 0x00..0x13；原版脚本里 0 条，
Steam 侧 26 条）。它集中出现在各路线结局/尾声与 `CG_ACHIEVEMENT` 的 CG 计数阈值处。
`present-ops.json` 曾把它误判成「UnkScreen 屏幕特效 / use_orig」；接缝重建的
`replace`/`delete` 块整块取原版，于是 Steam 的成就调用被丢掉：

* `yozora_koro_132_ep2`：`0xf0 03`（路线通关）、`0xf0 08`（尾声）、`0xf0 0c`（ころな专属）
  三条全丢（`0x0c` 全库唯一 ⇒ 该成就不可达）；
* `yozora_ori_130`：`0xf0 03` 丢失。

规则：逐个被替换的 Steam 脚本，取它写过的 **distinct `0xf0` id（按首次出现顺序）**，在替代
脚本的末尾结算段（最后一个 `0x07`/`0xff` 之前）补回；`0xf0` 是幂等的成就解锁，重复调用无害，
但必须保证执行路径能走到。插入点在脚本尾部 ⇒ 只影响其后指令的绝对偏移（若有跳转指向尾部，
按 `+payload` 重定位），不触碰前面的指令。

保护对象是**所有** Steam 有、原版 0 条的 opcode（`0xf0` 是其中一例）；策略自洽闸
（`orig==0` 不得 `use_orig`）在 `script/checks/check_cg_unlock.py`。

用法: python script/seam/preserve_achievements.py [--apply]
"""
import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tool import arcbuild, ws2, ws2disasm, ws2patch                 # noqa: E402

STEAM_RIO = ROOT / 'backup' / 'Rio.arc'
PATCH_RIO = ROOT / 'asset' / 'Rio.arc'


def scripts_of(path):
    out = {}
    for nb, data in arcbuild.read_raw(path):
        name = nb.decode('utf-16le')
        if name.upper().endswith('.WS2'):
            out[name.upper()] = data
    return out


def replacement_of(steam_name):
    base = steam_name[:-4]
    if not base.endswith('_E'):
        return None
    return base[:-2] + '.WS2'


def ach_ids(raw):
    out = []
    for ins in ws2disasm.disassemble(ws2.decode(raw)):
        if ins.opcode == 0xf0:
            aid = ins.operands[0]
            if aid not in out:
                out.append(aid)
    return out


def targets(ins):
    ops = ins.operands
    if ins.opcode == ws2patch.COND:
        return [int.from_bytes(ops[7:11], 'little'),
                int.from_bytes(ops[11:15], 'little')]
    if ins.opcode in (ws2patch.JUMP2, ws2patch.JUMP):
        return [int.from_bytes(ops[0:4], 'little')]
    return []


def insert_before_last_transition(decoded, payload):
    """在最后一个 0x07/0xff 之前插入 payload；尾部被跳转引用时按插入长度重定位。"""
    ins = ws2disasm.disassemble(decoded)
    last = len(ins) - 1
    if ins[last].opcode == 0xff and last > 0:
        last -= 1                     # 0xff 是终止符，插在它前一条（通常是 0x07）之前
    off = ins[last].offset
    shift = len(payload)

    def move(old):
        return old + shift if old and old >= off else old

    out = bytearray()
    for k, i in enumerate(ins):
        if k == last:
            out += payload
        if i.opcode in (ws2patch.COND, ws2patch.JUMP2, ws2patch.JUMP):
            out += bytes([i.opcode]) + ws2patch.rewrite_targets(i.operands, i.opcode, move)
        else:
            out += bytes([i.opcode]) + i.operands
    return bytes(out), ins, last


def verify(old_ins, new_data, payload, last):
    new_ins = ws2disasm.disassemble(new_data)
    assert sum(i.size for i in new_ins) == len(new_data), '新体未 100% tile'
    off = old_ins[last].offset
    shift = len(payload)
    assert len(payload) % 2 == 0, 'payload 不是 0xf0 序列'
    n_f0 = len(payload) // 2

    def move(old):
        return old + shift if old and old >= off else old

    expected = []
    for o in old_ins[:last]:
        ops = ws2patch.rewrite_targets(o.operands, o.opcode, move)             if o.opcode in (ws2patch.COND, ws2patch.JUMP2, ws2patch.JUMP) else o.operands
        expected.append((o.opcode, o.size, ops,
                         o.offset + (shift if o.offset >= off else 0)))
    for j in range(n_f0):
        expected.append((0xf0, 2, bytes([payload[2 * j + 1]]), off + 2 * j))
    for o in old_ins[last:]:
        ops = ws2patch.rewrite_targets(o.operands, o.opcode, move)             if o.opcode in (ws2patch.COND, ws2patch.JUMP2, ws2patch.JUMP) else o.operands
        expected.append((o.opcode, o.size, ops,
                         o.offset + (shift if o.offset >= off else 0)))

    assert len(new_ins) == len(expected),         '指令数不符：%d != %d' % (len(new_ins), len(expected))
    for got, (op, size, ops, noff) in zip(new_ins, expected):
        assert (got.opcode, got.size, got.operands, got.offset) == (op, size, ops, noff),             '指令不一致 @%d' % noff
    assert not ws2patch.check_boundaries(new_ins), '跳转目标非指令边界'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')

    steam = scripts_of(STEAM_RIO)
    patch = {nb.decode('utf-16le').upper(): (nb, d)
             for nb, d in arcbuild.read_raw(PATCH_RIO)}

    todo = {}
    for sname in sorted(steam):
        rname = replacement_of(sname)
        if rname is None or rname not in patch:
            continue
        want = ach_ids(steam[sname])
        if not want:
            continue
        have = set(ach_ids(patch[rname][1]))
        missing = [x for x in want if x not in have]
        if not missing:
            continue
        payload = b''.join(b'\xf0' + bytes([x]) for x in missing)
        data = ws2.decode(patch[rname][1])
        new, old_ins, last = insert_before_last_transition(data, payload)
        verify(old_ins, new, payload, last)
        todo[rname] = ws2.encode(new)
        print('  %-30s -> %-26s 补 0xf0 %s（%d -> %d B）'
              % (sname, rname, missing, len(data), len(new)))

    if not todo:
        print('无需改动（全部 0xf0 成就调用已守恒）')
        return 0
    if not a.apply:
        print('\n（dry-run，未写入；加 --apply 执行）')
        return 0

    bak = PATCH_RIO.with_name(PATCH_RIO.name + '.before_ach_preserve')
    if not bak.exists():
        shutil.copy2(PATCH_RIO, bak)
        print('已备份 %s' % bak.name)

    out = [(nb, todo.get(nb.decode('utf-16le').upper(), d))
           for nb, d in patch.values()]
    arcbuild.write_arc(out, PATCH_RIO)
    arcbuild.verify(PATCH_RIO, expect_count=len(out))
    back = {nb.decode('utf-16le').upper(): d
            for nb, d in arcbuild.read_raw(PATCH_RIO)}
    for name, data_bytes in todo.items():
        assert back[name] == data_bytes, '%s 回读不一致' % name
    print('\n已写入 %d 个脚本；回读一致' % len(todo))
    return 0


if __name__ == '__main__':
    sys.exit(main())
