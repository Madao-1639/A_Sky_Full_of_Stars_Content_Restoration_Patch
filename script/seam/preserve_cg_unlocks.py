"""把被替换 Steam 脚本里的 CG 解锁位点搬运到替代脚本（Cross_Channel 规则的本作移植）。

背景（doc/file-formats.md「CG 显示的固有 id 对」）：
画廊 CG 的 `0x34 …PNA 00 01 01` 后跟一对 `0b <A> 01 0b <B> 01`（A=1120..1228 CG 组，
B=1250..1659 画廊条目），`CG_ACHIEVEMENT` 再数这 410 个 B 发成就。还原把 Steam 删节段
整块换成原版内容时，原版用了**原版编号**的 A/B，Steam 段的解锁位点就丢了 ——
画廊条目永久锁、全 CG 成就（阈值 410）不可达。

规则（与 Cross_Channel 的 `_keep_groups()` 同构）：
  逐个被替换的 Steam 脚本（`<id>_E` → `<id>`，含 `_H_E` → `_H`），取其 **distinct (A,B) 对
  （按首次出现顺序）**，把替代脚本里缺的对以 `0b A 01 0b B 01` 重放到脚本入口；
  Steam 原有 `CG_ACHIEVEMENT` 而替代脚本一个都没有时，补一个调用。
  **不按全库去重** —— 别的脚本/路线有置位点不代表本场景的时机与路线已覆盖。

实现约束：
* 插入点在指令流最前端，其后全部绝对偏移（0x01 Condition / 0x02 Jump2 /
  0x06 Jump）整体 +len(payload)；插入后重定位并逐条自检。
* EVRET 的 field1/field2 是「指向 gallery `0b` 的绝对偏移」→ 插入后按标记位置重算
  （与 script/tools/fix_evret_offsets.py 同一规则，幂等）。
* 只读 backup/Rio.arc 作 Steam 基线；写 asset/Rio.arc，先备份、回读校验。

用法: python script/seam/preserve_cg_unlocks.py [--apply]
"""
import argparse
import shutil
import struct
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


def distinct_pairs(raw):
    seen, out = set(), []
    for m in ws2.DISPLAY.finditer(ws2.decode(raw)):
        pair = (struct.unpack('<H', m.group(3))[0],
                struct.unpack('<H', m.group(4))[0])
        if pair not in seen:
            seen.add(pair)
            out.append(pair)
    return out


def flag_ids(raw):
    """脚本里所有 `0b <u16> 01` 置位的 id（只看 CG 组 / 画廊条目域）。

    注入后重放的解锁组是**独立的 0b**（不再带 0x34 显示），所以幂等判断必须按旗标 id，
    不能按「显示位点后的 id 对」。
    """
    out = set()
    for ins in ws2disasm.disassemble(ws2.decode(raw)):
        if ins.opcode == 0x0b and len(ins.operands) >= 3                 and ins.operands[2] == 0x01:
            fid = int.from_bytes(ins.operands[0:2], 'little')
            if 1120 <= fid <= 2300:
                out.add(fid)
    return out


def ach_calls(raw):
    return ws2.decode(raw).count(ws2.ACH_CALL)


def evret_fix(decoded):
    """把 EVRET field1/field2 指回 `0b <gallery> 01`；返回 (bytes, 是否改动)。"""
    pos = decoded.find(b'\x07EVRET\x00')
    if pos < 0:
        return decoded, False
    target = pos + 7                       # 07EVRET\0 之后就是 0b 指令
    old1 = struct.unpack('<I', decoded[pos - 20:pos - 16])[0]
    old2 = struct.unpack('<I', decoded[pos - 4:pos])[0]
    if old1 == target and old2 == target:
        return decoded, False
    out = bytearray(decoded)
    out[pos - 20:pos - 16] = struct.pack('<I', target)
    out[pos - 4:pos] = struct.pack('<I', target)
    return bytes(out), True


def targets(ins):
    """指令引用的绝对偏移（与 ws2patch.rewrite_targets 同一读序）。"""
    ops = ins.operands
    if ins.opcode == ws2patch.COND:
        return [int.from_bytes(ops[7:11], 'little'),
                int.from_bytes(ops[11:15], 'little')]
    if ins.opcode in (ws2patch.JUMP2, ws2patch.JUMP):
        return [int.from_bytes(ops[0:4], 'little')]
    return []


def inject_at_entry(decoded, payload):
    """在指令流最前端插入 payload，并重定位其后全部绝对偏移。"""
    old = ws2disasm.disassemble(decoded)
    shift = len(payload)

    def move(old_off):
        return old_off + shift if old_off else 0

    out = bytearray(payload)
    for ins in old:
        ops = ws2patch.rewrite_targets(ins.operands, ins.opcode, move)
        out += bytes([ins.opcode]) + ops
    return bytes(out), old


def verify(old_ins, new_data, payload):
    """强不变式：tile、指令序列、跳转位移、非偏移操作数。"""
    new_ins = ws2disasm.disassemble(new_data)
    assert sum(i.size for i in new_ins) == len(new_data), '新体未 100% tile'

    pay_ins = ws2disasm.disassemble(payload)
    assert sum(i.size for i in pay_ins) == len(payload), 'payload 未 100% tile'
    for got, want in zip(new_ins, pay_ins):
        assert (got.offset, got.opcode, got.size, got.operands) == \
               (want.offset, want.opcode, want.size, want.operands), \
               'payload 指令不一致 @%d' % want.offset

    body = new_ins[len(pay_ins):]
    assert len(body) == len(old_ins), \
        '指令数不符：旧 %d 新 %d' % (len(old_ins), len(body))
    shift = len(payload)
    for o, n in zip(old_ins, body):
        assert o.opcode == n.opcode, 'opcode 序列不符 @%d' % o.offset
        assert o.offset + shift == n.offset, '指令位移不符 @%d' % o.offset
        if o.opcode in (ws2patch.COND, ws2patch.JUMP2, ws2patch.JUMP):
            for to, tn in zip(targets(o), targets(n)):
                expect = to + shift if to else 0
                assert tn == expect, \
                    '跳转目标未按位移重写 @%d：%s != %s' % (o.offset, tn, expect)
        else:
            assert o.operands == n.operands, \
                '非偏移操作数被改动 @%d op=0x%02x' % (o.offset, o.opcode)
    bad = ws2patch.check_boundaries(new_ins)
    assert not bad, '跳转目标非指令边界：%s' % bad[:5]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')

    steam = scripts_of(STEAM_RIO)
    patch = {nb.decode('utf-16le').upper(): (nb, d)
             for nb, d in arcbuild.read_raw(PATCH_RIO)}

    todo, changed = {}, []
    for sname in sorted(steam):
        rname = replacement_of(sname)
        if rname is None or rname not in patch:
            continue
        sp = distinct_pairs(steam[sname])
        have = flag_ids(patch[rname][1])
        missing = [p for p in sp if not (p[0] in have and p[1] in have)]
        sc, pc = ach_calls(steam[sname]), ach_calls(patch[rname][1])
        need_ach = bool(sc) and not pc
        if not missing and not need_ach:
            continue

        payload = bytearray()
        for aid, bid in missing:
            payload += b'\x0b' + struct.pack('<H', aid) + b'\x01'
            payload += b'\x0b' + struct.pack('<H', bid) + b'\x01'
            if sc:
                payload += ws2.ACH_CALL        # 每个重放组后跟一次成就子调用
        if need_ach and not missing:
            payload += ws2.ACH_CALL
        payload = bytes(payload)

        data = ws2.decode(patch[rname][1])
        new, old_ins = inject_at_entry(data, payload)
        new, evret = evret_fix(new)
        verify(old_ins, new, payload)
        todo[rname] = ws2.encode(new)
        changed.append((sname, rname, len(missing), need_ach,
                        len(data), len(new), evret))
        print('  %-30s -> %-26s 补 %2d 对%s  %d -> %d B%s'
              % (sname, rname, len(missing),
                 ' + 成就调用' if need_ach else '',
                 len(data), len(new), '  [EVRET 重算]' if evret else ''))

    if not todo:
        print('无需改动（全部解锁位点已守恒）')
        return 0
    if not a.apply:
        print('\n（dry-run，未写入；加 --apply 执行）')
        return 0

    bak = PATCH_RIO.with_name(PATCH_RIO.name + '.before_cg_unlock_preserve')
    if not bak.exists():
        shutil.copy2(PATCH_RIO, bak)
        print('已备份 %s' % bak.name)

    out = [(nb, todo.get(nb.decode('utf-16le').upper(), d))
           for nb, d in patch.values()]
    arcbuild.write_arc(out, PATCH_RIO)
    arcbuild.verify(PATCH_RIO, expect_count=len(out))
    back = {nb.decode('utf-16le').upper(): d
            for nb, d in arcbuild.read_raw(PATCH_RIO)}
    for name, data in todo.items():
        assert back[name] == data, '%s 回读不一致' % name
    print('\n已写入 %d 个脚本；回读一致' % len(todo))
    return 0


if __name__ == '__main__':
    sys.exit(main())
