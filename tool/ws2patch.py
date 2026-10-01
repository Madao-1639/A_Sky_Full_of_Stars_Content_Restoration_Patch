"""WS2 脚本字节补丁的共享原语：绝对偏移重定位、跳转边界自检、调用边扫描、opcode 策略加载。

消费者：script/seam/build_seam.py、inject_achievements.py、revert_isolation.py、
gen_worklist.py、remove_bypassed.py（原各脚本内联实现，2026-10 整合为一处；
算法为逐字节搬移，未改语义）。

背景：`0x01 Condition`（ops[7:11]=a、ops[11:15]=b）、`0x02 Jump2`（ops[0:4]）、
`0x06 Jump`（ops[0:4]）的操作数是**文件内绝对偏移**。凡在指令流中做的字节增删
（拼接、改名、注入），这些目标都必须按累积位移重写，并回读校验每个目标落在
指令边界上（目标 0 = "不跳转"哨兵，跳过）。
"""
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent

# ---- 项目公共路径 -----------------------------------------------------------
ASSET_RIO = ROOT / 'asset' / 'Rio.arc'
ZH_RIO = ROOT / 'asset' / 'zh-CN' / 'Rio.arc'
GRAPHIC_RIO = ROOT / 'asset' / 'Graphic.arc'
BACKUP_RIO = ROOT / 'backup' / 'Rio.arc'
# 日文原版安装目录（仓库外、与仓库同级的游戏中文名目录；backup/ 是 Steam 基线，不是原版）
JP_DIR = ROOT.parent / '抬头看看吧看那天上的繁星'
JP_RIO = JP_DIR / 'Rio.arc'

JUMP2, COND, JUMP = 0x02, 0x01, 0x06

_OPS_JSON = ROOT / 'resource' / 'present-ops.json'


def load_present_ops(path=None):
    """读取 opcode 策略表（resource/present-ops.json）。

    返回 (by_opcode, by_name, ops)：
      by_opcode  {int(opcode,16): policy 字符串}
      by_name    {name 小写: 完整 op 条目}
      ops        原始条目列表
    """
    ops = json.loads((_OPS_JSON if path is None else Path(path)).read_text(encoding='utf-8'))['ops']
    by_opcode = {int(o['opcode'], 16): o['policy'] for o in ops}
    by_name = {o['name'].lower(): o for o in ops}
    return by_opcode, by_name, ops


def is_ach(ins):
    """是否为成就调用指令（0x04 + `CG_ACHIEVEMENT`）。"""
    return ins.opcode == 0x04 and (ins.operands or b'').startswith(b'CG_ACHIEVEMENT\x00')


def jump_targets(ins):
    """该指令引用的**文件内绝对偏移**（Condition/Jump2/Jump）。"""
    f = ins.fields
    if ins.opcode == JUMP2:
        return [f.get('a')]
    if ins.opcode == COND:
        return [f.get('a'), f.get('b')]
    if ins.opcode == JUMP:
        return [f.get('a')]
    return []


def rewrite_targets(ops, opcode, fn):
    """按 fn(old)->new 重写一条指令操作数里的绝对偏移；返回新 operands（bytes/bytes）。

    `0x02 Jump2` 改 ops[0:4]；`0x01 Condition` 改 ops[7:11] 与 ops[11:15]；
    `0x06 Jump` 改 ops[0:4]。其余 opcode 原样返回。old == 0 是"不跳转"哨兵，不改。
    """
    ops = bytearray(ops)
    if opcode == JUMP2:
        old = int.from_bytes(ops[0:4], 'little')
        if old:
            ops[0:4] = (fn(old) & 0xFFFFFFFF).to_bytes(4, 'little')
    elif opcode == COND:
        for off in (7, 11):
            old = int.from_bytes(ops[off:off + 4], 'little')
            if old:
                ops[off:off + 4] = (fn(old) & 0xFFFFFFFF).to_bytes(4, 'little')
    elif opcode == JUMP:
        old = int.from_bytes(ops[0:4], 'little')
        if old:
            ops[0:4] = (fn(old) & 0xFFFFFFFF).to_bytes(4, 'little')
    return bytes(ops)


def check_boundaries(ins_list, skip_offsets=()):
    """绝对偏移硬自检：每个目标都必须落在指令边界上。

    返回违规列表 [(opcode, offset, target)]；目标 0 与 offset ∈ skip_offsets 跳过
    （skip 用于 build_seam 里被判为 inert 的疑似非指令）。
    """
    bounds = {i.offset for i in ins_list}
    bad = []
    for i in ins_list:
        if i.offset in skip_offsets:
            continue
        ops = i.operands
        if i.opcode == JUMP2:
            targets = [int.from_bytes(ops[0:4], 'little')]
        elif i.opcode == COND:
            targets = [int.from_bytes(ops[7:11], 'little'),
                       int.from_bytes(ops[11:15], 'little')]
        elif i.opcode == JUMP:
            targets = [int.from_bytes(ops[0:4], 'little')]
        else:
            continue
        for t in targets:
            if t and t not in bounds:
                bad.append((i.opcode, i.offset, t))
    return bad


_EDGE = re.compile(rb'[\x04\x07]([A-Z0-9_]{4,40})\x00')
_callers_cache = None


def call_graph(decoded_members, skip=()):
    """全脚本 `0x04 RunFile`/`0x07 NextFile` 调用边的反向索引。

    decoded_members: {成员名大写: ws2.decode 后的 bytes}；skip 里的成员不作为调用者。
    返回 {目标 stem + '.WS2': set(调用者成员名大写)}。
    """
    rev = defaultdict(set)
    for name, dec in decoded_members.items():
        if not name.endswith('.WS2') or name in skip:
            continue
        for m in _EDGE.finditer(dec):
            rev[m.group(1).decode('ascii') + '.WS2'].add(name)
    return rev


def callers_of(stem_e):
    """哪些脚本的 `0x04/0x07` 指向 <stem_e>.WS2（读 asset/Rio.arc，带缓存）。"""
    global _callers_cache
    if _callers_cache is None:
        from tool import arcbuild, ws2
        members = {n.decode('utf-16le').upper(): ws2.decode(d)
                   for n, d in arcbuild.read_raw(ASSET_RIO)}
        _callers_cache = call_graph(members)
    return sorted(_callers_cache.get(stem_e.upper() + '.WS2', []))
