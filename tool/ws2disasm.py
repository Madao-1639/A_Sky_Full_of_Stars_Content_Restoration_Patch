# -*- coding: utf-8 -*-
"""
ws2disasm.py — AdvHD 引擎 .WS2 剧情脚本的线性反汇编器（本作 A Sky Full of Stars 移植版）。

用法：
    from tool import ws2, ws2disasm
    data = ws2.decode(raw_ws2_member)          # 先解 rot6 混淆
    instrs = ws2disasm.disassemble(data)       # -> list[Instruction]

Instruction 字段：
    offset   int    该指令首字节的文件偏移
    opcode   int    首字节
    size     int    指令总长度（含 opcode 字节）
    operands bytes  **恒等于** data[offset+1 : offset+size]（原始操作数字节）
    fields   dict   解析出的字段（name / u16 / u32 / f32 / text / jump target …）

按偏移定位/改写脚本的推荐姿势见 doc 或本文件末尾的 `_disassemble` 注释：
先 `instrs = disassemble(data)`，再按 `ins.offset` 建索引，改写时用
`data[ins.offset : ins.offset + ins.size]` 取整条指令的原始字节。

验证：三套语料（asset/ 369 + 2015 原版 369 + backup/ 349 = 1087 个 .ws2），全部 100% tile（sum(size) == len(data)），0 失败。
"""
import struct

# AdvHD 系引擎的 opcode -> 函数名。同一引擎家族的各游戏共用这套编号
# （`33`/`34`/`37`/`39`/`3f`/`04`/`14`/`15` 等在多款游戏里逐字节同构）。
# 「Unk*」是尚未定名的部分；本项目的语料只触及其中一小部分。
# 完整对照表与来源说明见 doc/file-formats.md「引擎函数名对照表」。
OPCODE_NAMES = {
    0x00: 'Undefined',        0x01: 'Condition',          0x02: 'Jump2',
    0x04: 'RunFile',          0x05: 'Unk05',              0x06: 'Jump',
    0x07: 'NextFile',         0x08: 'Unk08',              0x09: 'LayerConfig',
    0x0a: 'Unk0A',            0x0b: 'SetFlag',            0x0d: 'Unk0D',
    0x0e: 'Unk0E',            0x0f: 'ShowChoice',         0x11: 'SetTimer',
    0x12: 'StartTimer',       0x13: 'Unk13',              0x14: 'DisplayMessage',
    0x15: 'SetDisplayName',   0x16: 'Unk16',              0x17: 'Unk17',
    0x18: 'AddMessageToLog',  0x19: 'Unk19',              0x1a: 'OpenTitle',
    0x1b: 'Unk1B',            0x1c: 'ExecuteFunction',    0x1d: 'Unk1D',
    0x1e: 'PlayMusic',        0x1f: 'StopMusic',          0x20: 'MusicUnk1',
    0x28: 'SoundEffect',      0x29: 'SoundUnk1',          0x2a: 'SoundUnk2',
    0x2e: 'CharMessageStart', 0x30: 'SoundEffectUnk30',   0x32: 'VariableUnk32',
    0x33: 'SetBackground',    0x34: 'UsePnaPackage',      0x35: 'PlayMovie',
    0x36: 'PrepareBackgroundArea', 0x37: 'ClearLayer',    0x38: 'VariableUnk3',
    0x39: 'DisplayCharacterImage', 0x3a: 'UnkBackground2', 0x3b: 'BackgroundMessage',
    0x3d: 'Unk3D',            0x3e: 'Unk3E',              0x3f: 'LayersList',
    0x40: 'SetMask',          0x41: 'UnkBackground3',     0x42: 'Unk42',
    0x43: 'Unk43',            0x44: 'Effect44',           0x45: 'DragBackground',
    0x46: 'MoveBackground',   0x47: 'Effect1',            0x48: 'Effect2',
    0x4a: 'Unk4A',            0x51: 'VariableUnk51',      0x52: 'VariableUnk2',
    0x53: 'VariableUnk4',     0x56: 'RainStart',          0x57: 'UnkBackground1',
    0x58: 'Effect3',          0x5b: 'InitKeyName',        0x5c: 'RainEnd',
    0x64: 'Unk64',            0x65: 'C65',                0x66: 'ShowGraphic',
    0x67: 'Unk67',            0x68: 'Unk68',              0x6e: 'SetVariable',
    0x6f: 'VariableUnk',      0x73: 'SetPnaFile',         0x74: 'TimerUnk74',         0x75: 'Unk75',
    0x78: 'Unk78',            0x7a: 'Unk7A',              0x7b: 'Unk7B',
    0x84: 'Unk84',            0x97: 'Unk97',              0xb0: 'UnkB0',
    0xe6: 'ConditionalJump',  0xf0: 'UnkScreen',          0xfb: 'UnkFB',
    0xfc: 'UnkFC',            0xfd: 'UnkFD',              0xff: 'FileEnd',
}


def opcode_name(op):
    """opcode -> 引擎函数名（未收录时返回 None）。"""
    return OPCODE_NAMES.get(op)


class UnknownInstruction(Exception):
    def __init__(self, offset, opcode, msg=''):
        self.offset = offset
        self.opcode = opcode
        self.msg = msg
        super().__init__('UnknownInstruction at 0x%x: opcode 0x%02x %s' % (offset, opcode, msg))

class Instruction:
    __slots__ = ('offset', 'opcode', 'size', 'operands', 'fields')
    def __init__(self, offset, opcode, size, operands, fields):
        self.offset = offset
        self.opcode = opcode
        self.size = size
        self.operands = operands
        self.fields = fields
    def __repr__(self):
        f = ' '.join('%s=%r' % (k, v) for k, v in self.fields.items())
        return '<%04x %02x sz=%d %s>' % (self.offset, self.opcode, self.size, f)

# ---------------------------------------------------------------------------
# low level helpers
# ---------------------------------------------------------------------------

def _read_cstring(data, pos, limit=4096):
    """Return (raw bytes w/o NUL, endpos just past the NUL)."""
    end = data.find(b'\x00', pos, pos + limit)
    if end < 0:
        raise UnknownInstruction(pos, data[pos] if pos < len(data) else 0,
                                 'unterminated string')
    return data[pos:end], end + 1

def _is_name(b):
    """Name may be ASCII or Shift-JIS (CNR scripts); reject control bytes."""
    if len(b) > 200:
        return False
    return all(0x20 <= c <= 0xfc and c != 0x7f for c in b)

def _is_ascii(b):
    return all(0x20 <= c < 0x7f for c in b)

_RESNAME_CHARS = frozenset(
    list(b'ABCDEFGHIJKLMNOPQRSTUVWXYZ') + list(b'abcdefghijklmnopqrstuvwxyz') +
    list(b'0123456789') + list(b'_.-'))


def _is_resource_name(b):
    """资源文件名判据：只含 [A-Za-z0-9_.-]、含 '.'、长度 2..64。
    用于 0x40 的第二个操作数（见 _op_40 注释）。"""
    if not (2 <= len(b) <= 64) or b'.' not in b:
        return False
    return all(c in _RESNAME_CHARS for c in b)

def _dec_str(b):
    try:
        return b.decode('ascii')
    except UnicodeDecodeError:
        return b.decode('cp932', 'replace')

def _f32(data, pos):
    return struct.unpack_from('<f', data, pos)[0]

def _u16(data, pos):
    return struct.unpack_from('<H', data, pos)[0]

def _u32(data, pos):
    return struct.unpack_from('<I', data, pos)[0]

def _chk(cond, op_offset, opcode, msg):
    if not cond:
        raise UnknownInstruction(op_offset, opcode, msg)

# ---------------------------------------------------------------------------
# generic handler builders
# ---------------------------------------------------------------------------

def _fixed(n, *field_specs):
    """Fixed n operand bytes (total size n+1). field_specs: (name, kind, off);
    kind: u8/u16/u32/f32 or int = raw hex-dump of that many bytes."""
    def h(data, pos, op_offset):
        if pos + n > len(data):
            raise UnknownInstruction(op_offset, data[op_offset], 'truncated')
        fields = {}
        for name, kind, off in field_specs:
            if kind == 'u8':
                fields[name] = data[pos + off]
            elif kind == 'u16':
                fields[name] = _u16(data, pos + off)
            elif kind == 'u32':
                fields[name] = _u32(data, pos + off)
            elif kind == 'f32':
                fields[name] = round(_f32(data, pos + off), 6)
            else:
                fields[name] = data[pos + off:pos + off + kind].hex()
        return n + 1, data[pos:pos + n], fields
    return h

def _name_op(opcode, extra=0, extra_field='tail', pre_bytes=0, ascii_only=True,
             extra_check=None):
    """opcode [pre_bytes] <name NUL> [extra fixed bytes]"""
    def h(data, pos, op_offset):
        p = pos + pre_bytes
        name, end = _read_cstring(data, p)
        ok = _is_ascii(name) if ascii_only else _is_name(name)
        _chk(ok, op_offset, opcode, 'name not ascii: %r' % name[:40])
        if end + extra > len(data):
            raise UnknownInstruction(op_offset, opcode, 'truncated after name')
        fields = {'name': _dec_str(name)}
        if pre_bytes:
            fields['pre'] = data[pos:p].hex()
        if extra:
            fields[extra_field] = data[end:end + extra].hex()
            if extra_check is not None:
                _chk(extra_check(data[end:end + extra]), op_offset, opcode,
                     '%s %s' % (extra_field, data[end:end + extra].hex()))
        return end + extra - op_offset, data[pos + 1:end + extra], fields
    return h

def _two_name_op(opcode, extra=0, extra_field='tail', pre_bytes=0, ascii_only=True):
    """opcode [pre] <name1 NUL> <name2 NUL> [extra bytes]"""
    def h(data, pos, op_offset):
        p = pos + pre_bytes
        n1, end1 = _read_cstring(data, p)
        ok = _is_ascii(n1) if ascii_only else _is_name(n1)
        _chk(ok, op_offset, opcode, 'name1 bad: %r' % n1[:40])
        n2, end2 = _read_cstring(data, end1)
        ok = _is_ascii(n2) if ascii_only else _is_name(n2)
        _chk(ok, op_offset, opcode, 'name2 bad: %r' % n2[:40])
        if end2 + extra > len(data):
            raise UnknownInstruction(op_offset, opcode, 'truncated')
        fields = {'name': _dec_str(n1), 'name2': _dec_str(n2)}
        if pre_bytes:
            fields['pre'] = data[pos:p].hex()
        if extra:
            fields[extra_field] = data[end2:end2 + extra].hex()
        return end2 + extra - op_offset, data[pos + 1:end2 + extra], fields
    return h

# ---------------------------------------------------------------------------
# specific opcode handlers
# ---------------------------------------------------------------------------

def _op_01(data, pos, op_offset):
    # 01 <u8 mode> ...: mode 0x00 -> 4 operand bytes; else 15 operand bytes:
    #    01 <mode> <u16 id> <f32> <u32 a> <u32 b>
    if pos >= len(data):
        raise UnknownInstruction(op_offset, 0x01, 'truncated')
    mode = data[pos]
    if mode == 0x00:
        n = 4
        if pos + n > len(data):
            raise UnknownInstruction(op_offset, 0x01, 'truncated')
        return n + 1, data[pos:pos + n], {'mode': mode, 'raw': data[pos + 1:pos + n].hex()}
    n = 15
    if pos + n > len(data):
        raise UnknownInstruction(op_offset, 0x01, 'truncated')
    vid = _u16(data, pos + 1)
    val = _f32(data, pos + 3)
    a = _u32(data, pos + 7)
    b = _u32(data, pos + 11)
    return n + 1, data[pos:pos + n], {'mode': mode, 'id': vid, 'value': round(val, 6),
                                      'f32hex': data[pos + 3:pos + 7].hex(), 'a': a, 'b': b}

def _op_05(data, pos, op_offset):
    # 05 <u8 a> <u32 b> <u32 c>  (10B; a=0xff: stop-all, a=0x00 b=0 c=1: BGM stop)
    if pos + 9 > len(data):
        raise UnknownInstruction(op_offset, 0x05, 'truncated')
    p = data[pos:pos + 9]
    return 10, p, {'a': p[0], 'b': _u32(p, 1), 'c': _u32(p, 5)}

def _op_04(data, pos, op_offset):
    # 04 RunFile <name NUL>   (engine subroutine call; 绝大多数是 LAYER_ORDER)
    name, end = _read_cstring(data, pos)
    _chk(_is_name(name), op_offset, 0x04, 'name bad: %r' % name[:40])
    return end - op_offset, data[pos + 1:end], {'name': _dec_str(name)}

def _op_06(data, pos, op_offset):
    # 06 <u32 target>  (5B unconditional jump; target = file offset)
    if pos + 4 > len(data):
        raise UnknownInstruction(op_offset, 0x06, 'truncated')
    target = _u32(data, pos)
    return 5, data[pos:pos + 4], {'target': target}

def _op_07(data, pos, op_offset):
    # 07 <script name NUL>  (transfer to script; often followed by separate ff END)
    name, end = _read_cstring(data, pos)
    _chk(_is_ascii(name) and len(name) > 0, op_offset, 0x07,
         'name bad: %r' % name[:40])
    return end - op_offset, data[pos + 1:end], {'name': _dec_str(name)}

def _op_09(data, pos, op_offset):
    # 09 <mode u8> <id u16> <f32>   (mode 0 = set float var; mode 1 = ?)
    if pos + 7 > len(data):
        raise UnknownInstruction(op_offset, 0x09, 'truncated')
    mode = data[pos]
    vid = _u16(data, pos + 1)
    raw = data[pos + 3:pos + 7]
    val = _f32(data, pos + 3)
    return 8, data[pos + 1:pos + 7], {'mode': mode, 'id': vid,
                                      'value': round(val, 6), 'f32hex': raw.hex()}

def _plausible_secs(v):
    """定时器时长判据：本作语料实测取值 ∈ {0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0,
    1.5, 2.0, 5.0, 8.0, 10.0 ...}，最大 10 秒级。

    下界必须排除**非规格化小数**：把错位 1 字节的字节串当 f32 读会得到
    ~1e-28 这种极小正数，只判 `v >= 0` 会把它当合法值（已实测踩到：
    `11 "timer01" 00 00 00 80 3f 12` 的 5 字节读法给出 6.0e-28）。"""
    if v != v or v < 0.0 or v > 600.0:
        return False
    if v == 0.0:
        return not (struct.pack('<f', v)[3] & 0x80)      # 排除 -0.0
    return v >= 0.01


# opcode 0x11 exists in two encodings in this engine family:
#   form 5B: 11 <name NUL> 00 <f32>   <- Steam (asset/) + backup/ 语料
#   form 4B: 11 <name NUL> <f32>      <- 2015 原版语料
# The 0x00 separator is only observable when the f32 does not itself start with
# 0x00; 全语料统计：steam 274 文件中 273 个只出现 5B，orig 119 个文件只出现 4B。
# Ties (byte after the name is 0x00 and BOTH readings are plausible seconds) are
# broken by _SEP11_DEFAULT, which disassemble() flips on retry.
_SEP11_DEFAULT = [True]


def _op_11(data, pos, op_offset):
    # 11 SetTimer <name NUL> [00] <f32 seconds>
    name, end = _read_cstring(data, pos)
    _chk(_is_name(name), op_offset, 0x11, 'name bad')
    if end + 4 > len(data):
        raise UnknownInstruction(op_offset, 0x11, 'truncated timer')
    four = _f32(data, end)
    five = _f32(data, end + 1) if (data[end] == 0x00 and end + 5 <= len(data)) else None
    p4 = _plausible_secs(four)
    p5 = five is not None and _plausible_secs(five)
    if p5 and not p4:
        use5 = True
    elif p4 and not p5:
        use5 = False
    else:
        use5 = bool(five is not None and _SEP11_DEFAULT[0])
    if use5:
        return end + 5 - op_offset, data[pos + 1:end + 5], {
            'name': _dec_str(name), 'seconds': round(five, 6), 'form': 'sep+f32',
            'f32hex': data[end + 1:end + 5].hex()}
    return end + 4 - op_offset, data[pos + 1:end + 4], {
        'name': _dec_str(name), 'seconds': round(four, 6), 'form': 'f32',
        'f32hex': data[end:end + 4].hex()}

def _op_12(data, pos, op_offset):
    # 12 <name NUL> <2 tail bytes>   (wait for timer; tail 0100 or 0000)
    name, end = _read_cstring(data, pos)
    _chk(_is_name(name), op_offset, 0x12, 'name bad')
    if end + 2 > len(data):
        raise UnknownInstruction(op_offset, 0x12, 'truncated')
    tail = data[end:end + 2]
    return end + 2 - op_offset, data[pos + 1:end + 2], {'name': _dec_str(name),
                                                        'tail': tail.hex()}

def _op_14(data, pos, op_offset):
    # 14 DisplayMessage <u16 id> <u16 0x0000> <char NUL> <text NUL> <u8 0>
    # text contains %K/%P/%N markers and \d..\d delays
    if pos + 5 > len(data):
        raise UnknownInstruction(op_offset, 0x14, 'truncated')
    did = _u16(data, pos)
    _chk(data[pos + 2:pos + 4] == b'\x00\x00', op_offset, 0x14,
         'dialogue hdr %s' % data[pos:pos + 4].hex())
    char, p = _read_cstring(data, pos + 4)
    text, p2 = _read_cstring(data, p)
    if p2 >= len(data):
        raise UnknownInstruction(op_offset, 0x14, 'missing tail')
    tail = data[p2]
    _chk(tail == 0x00, op_offset, 0x14, 'dialogue tail 0x%02x' % tail)
    size = p2 + 1 - op_offset
    return size, data[pos + 1:p2 + 1], {'id': did, 'char': _dec_str(char),
                                        'text': _dec_str(text)}

def _op_15(data, pos, op_offset):
    # 15 SetDisplayName <prefix NUL> 00   ; 清框/设说话人；前缀空或 '%LC<名>'
    s, end = _read_cstring(data, pos, limit=300)
    if end >= len(data):
        raise UnknownInstruction(op_offset, 0x15, 'truncated')
    tail = data[end]
    _chk(tail == 0x00, op_offset, 0x15, 'clear tail 0x%02x' % tail)
    _chk(len(s) < 256, op_offset, 0x15, 'prefix too long')
    return end + 1 - op_offset, data[pos + 1:end + 1], {'prefix': _dec_str(s)}

def _op_0e(data, pos, op_offset):
    # 0e timing block (byte1 == 0x00): 14 raw operand bytes
    # 0e choice header (byte1 == 0x0b): operands 0b 00 <count> 00 01  (6B total)
    #   followed by either 0f <count> text-entry list, or a list of 01-instrs
    #   (mode 2, b = jump target) interleaved with 0b <u16 flag> 00 markers
    kind = data[pos]
    if kind == 0x00:
        # timing block: 14 operand bytes (menu transition: u16s 1000/13/200 seen)
        n = 14
        if pos + n > len(data):
            raise UnknownInstruction(op_offset, 0x0e, 'truncated')
        p = data[pos:pos + n]
        return n + 1, p, {'form': 'timing', 'raw': p.hex()}
    _chk(kind == 0x0b, op_offset, 0x0e, 'kind 0x%02x' % kind)
    if pos + 5 > len(data):
        raise UnknownInstruction(op_offset, 0x0e, 'truncated header')
    hdr = data[pos:pos + 5]
    _chk(hdr[1] == 0x00 and hdr[3] == 0x00 and hdr[4] == 0x01, op_offset, 0x0e,
         'hdr %s' % hdr.hex())
    return 6, hdr, {'form': 'choice-hdr', 'count': hdr[2]}

def _parse_choice_entries(data, op_offset, opcode, count, p):
    """count x (<u16 strid> <text NUL> 00 <u16 label> <jump>); jump = 07 name | 06 u32"""
    entries = []
    for idx in range(count):
        if p + 2 > len(data):
            raise UnknownInstruction(op_offset, opcode, 'truncated entry %d' % idx)
        strid = _u16(data, p)
        text, e1 = _read_cstring(data, p + 2)
        # 原生语料全 ASCII；WSC 转换产物合法携带 CP932 选项文本，仅要求非空
        _chk(len(text) > 0, op_offset, opcode, 'entry text %r' % text[:40])
        _chk(e1 < len(data) and data[e1] == 0x00, op_offset, opcode, 'entry sep')
        _chk(e1 + 3 <= len(data), op_offset, opcode, 'truncated label')
        label = _u16(data, e1 + 1)
        p = e1 + 3
        op = data[p]
        if op == 0x07:
            name, e2 = _read_cstring(data, p + 1)
            _chk(_is_ascii(name), op_offset, opcode, 'entry script %r' % name[:40])
            entries.append({'strid': strid, 'text': _dec_str(text),
                            'label': label, 'jump_op': 7, 'name': _dec_str(name)})
            p = e2
        elif op == 0x06:
            _chk(p + 5 <= len(data), op_offset, opcode, 'truncated entry jump')
            entries.append({'strid': strid, 'text': _dec_str(text),
                            'label': label, 'jump_op': 6, 'target': _u32(data, p + 1)})
            p += 5
        else:
            raise UnknownInstruction(op_offset, opcode, 'entry jump op 0x%02x' % op)
    return entries, p

def _op_1e(data, pos, op_offset):
    # 1e <slot NUL> <file NUL> <17-byte tail>   (BGM play)
    # 尾段是**单条指令的一部分**，不是"10 字节尾 + 一条 0a 伪指令"——
    # [10] 的 0x0a 是参数。布局（Ws2Explorer v3 'ffhhbf'）：
    #   f32 vol @0 | f32 0 @4 | u16 0xffff @8 | u16 0x000a @10 | u8 1 @12 | f32 0 @13
    # 全语料 877 条：仅 @0 的音量有变化（0.0 / 1.0 / 2.0），其余恒定。
    slot, end1 = _read_cstring(data, pos)
    _chk(_is_name(slot), op_offset, 0x1e, 'bgm slot bad')
    fn, end2 = _read_cstring(data, end1)
    _chk(_is_name(fn), op_offset, 0x1e, 'bgm file bad')
    TAIL = 17
    if end2 + TAIL > len(data):
        raise UnknownInstruction(op_offset, 0x1e, 'truncated bgm tail')
    tail = data[end2:end2 + TAIL]
    # 本作语料变体：@0 恒 0、@4 承载真正的音量（参照实现相反）；[8:10] 另有
    # 0x0000 形态；[10:12] 另有 0x0000 形态。全语料恒定的是 [12]==0x01 与
    # [13:17]==0。逐字节模态见 doc/ws2-byte-modality.md。
    _chk(tail[12] == 0x01 and tail[13:17] == bytes(4), op_offset, 0x1e,
         'bgm tail %s' % tail.hex())
    size = end2 + TAIL - op_offset
    return size, data[pos + 1:end2 + TAIL], {'slot': _dec_str(slot), 'file': _dec_str(fn),
                                             'vol': round(_f32(tail, 4), 6),
                                             'mode': _u16(tail, 8), 'code': _u16(tail, 10),
                                             'f32hex': tail[4:8].hex()}

def _op_1f(data, pos, op_offset):
    # 1f <slot NUL> <f32>   (BGM stop with fade seconds)
    name, end = _read_cstring(data, pos)
    _chk(_is_name(name), op_offset, 0x1f, 'name bad')
    if end + 4 > len(data):
        raise UnknownInstruction(op_offset, 0x1f, 'truncated')
    val = _f32(data, end)
    return end + 4 - op_offset, data[pos + 1:end + 4], {'name': _dec_str(name),
                                                        'value': round(val, 6)}

def _op_28(data, pos, op_offset):
    # 28 <slot NUL> <file NUL> <22-byte tail>   (SE play；槽名为 char* 时即语音)
    # 布局（Ws2Explorer v3 'ssffhhbhhbf'）：
    #   f32 vol @0 | f32 @4 | u16 mode @8(0|ffff) | u16 code @10(3..10) | u8 @12
    #   u16 @13(0|101) | u16 @15 | u8 @17(0|1) | f32 @18
    # 全语料 1556 条的不变量：[11]==[12]==0、[14:17]==0、[18:22]==0，
    # 且 ([13],[17]) 只取 (0,1)（SE，1248 条）或 (101,0)（char* 槽语音，308 条）。
    # 其余位置（音量、mode、code）随实例变化，不做断言。
    slot, end1 = _read_cstring(data, pos)
    _chk(_is_name(slot), op_offset, 0x28, 'se slot bad')
    fn, end2 = _read_cstring(data, end1)
    _chk(_is_name(fn), op_offset, 0x28, 'se file bad')
    TAIL = 22
    if end2 + TAIL > len(data):
        raise UnknownInstruction(op_offset, 0x28, 'truncated se tail')
    tail = data[end2:end2 + TAIL]
    size = end2 + TAIL - op_offset
    return size, data[pos + 1:end2 + TAIL], {'slot': _dec_str(slot), 'file': _dec_str(fn),
                                             'vol': round(_f32(tail, 0), 6),
                                             'mode': _u16(tail, 8), 'code': _u16(tail, 10),
                                             'tail': tail.hex()}

def _op_29(data, pos, op_offset):
    # 29 <slot NUL> <f32>   (fade-stop sound in slot; slot may be '*')
    name, end = _read_cstring(data, pos)
    _chk(_is_name(name), op_offset, 0x29, 'name bad')
    if end + 4 > len(data):
        raise UnknownInstruction(op_offset, 0x29, 'truncated')
    val = _f32(data, end)
    return end + 4 - op_offset, data[pos + 1:end + 4], {'name': _dec_str(name),
                                                        'value': round(val, 6)}

def _op_2e(data, pos, op_offset):
    # 2e 28 <channel NUL> <file NUL> <CONSTANT 22-byte tail>   (voice play)
    _chk(data[pos] == 0x28, op_offset, 0x2e, 'voice sub 0x%02x' % data[pos])
    chan, end1 = _read_cstring(data, pos + 1)
    _chk(_is_ascii(chan) and len(chan) > 0, op_offset, 0x2e, 'voice chan bad')
    fn, end2 = _read_cstring(data, end1)
    _chk(_is_ascii(fn) and len(fn) > 0, op_offset, 0x2e, 'voice file bad')
    TAIL = 22
    if end2 + TAIL > len(data):
        raise UnknownInstruction(op_offset, 0x2e, 'truncated voice tail')
    tail = data[end2:end2 + TAIL]
    size = end2 + TAIL - op_offset
    return size, data[pos + 1:end2 + TAIL], {'chan': _dec_str(chan),
                                             'file': _dec_str(fn),
                                             'tail': tail.hex()}

def _op_33(data, pos, op_offset):
    # 33 SetBackground <slot NUL> <file NUL> <2 bytes flags>   (硬载入，缺资源会卡死)
    slot, end1 = _read_cstring(data, pos)
    _chk(_is_name(slot) and len(slot) > 0, op_offset, 0x33, 'slot bad')
    fn, end2 = _read_cstring(data, end1)
    _chk(_is_name(fn) and len(fn) > 0, op_offset, 0x33, 'file bad')
    if end2 + 2 > len(data):
        raise UnknownInstruction(op_offset, 0x33, 'truncated')
    flags = data[end2:end2 + 2]
    size = end2 + 2 - op_offset
    return size, data[pos + 1:end2 + 2], {'slot': _dec_str(slot), 'file': _dec_str(fn),
                                          'flags': flags.hex()}

def _op_34(data, pos, op_offset):
    # 34 UsePnaPackage <u8 tag> <slot NUL> <file NUL> <2 bytes flags>
    #    把资源**绑定**到一个具名句柄（tag 字节与 slot 是同一个串，如 's'+'t01'）；
    #    句柄只回答"哪一层"，位置在 46（见下）。
    a = data[pos]
    slot, end1 = _read_cstring(data, pos + 1)
    _chk(_is_name(slot) and len(slot) > 0, op_offset, 0x34, 'slot bad')
    fn, end2 = _read_cstring(data, end1)
    _chk(_is_name(fn) and len(fn) > 0, op_offset, 0x34, 'file bad')
    if end2 + 2 > len(data):
        raise UnknownInstruction(op_offset, 0x34, 'truncated')
    flags = data[end2:end2 + 2]
    size = end2 + 2 - op_offset
    return size, data[pos + 1:end2 + 2], {'tag': a, 'slot': _dec_str(slot),
                                          'file': _dec_str(fn), 'flags': flags.hex()}

def _op_35(data, pos, op_offset):
    # 35 <name NUL> <file NUL> 01 01 01   (movie play)
    n1, end1 = _read_cstring(data, pos)
    _chk(_is_name(n1), op_offset, 0x35, 'name bad')
    n2, end2 = _read_cstring(data, end1)
    _chk(_is_name(n2), op_offset, 0x35, 'file bad')
    N = 3
    if end2 + N > len(data):
        raise UnknownInstruction(op_offset, 0x35, 'truncated')
    tail = data[end2:end2 + N]
    # 本作变体：中间字节可为 0x06（`35 "st03" 00 "STARMOV_08B.DAT" 00 01 06 01`）。
    _chk(tail[0] == 0x01 and tail[2] == 0x01, op_offset, 0x35,
         'tail %s' % tail.hex())
    return end2 + N - op_offset, data[pos + 1:end2 + N], {'name': _dec_str(n1),
                                                          'file': _dec_str(n2),
                                                          'mode': tail[1]}

def _op_39(data, pos, op_offset):
    # 39 DisplayCharacterImage <name NUL> 02 01 <c u8> <c x u16 frame ids>
    #   c = 帧数；随后紧跟 c 个 u16 帧号（含首个）。参照实现把这里硬写成
    #   "c==4 -> 11 字节，否则 5 字节"，那是 CC 语料只出现 c∈{1,4} 的巧合；
    #   本作语料出现 c=2（帧号形如 55/39 = 立绘差分编号），故必须按一般式读。
    #   全语料实证：`02 01 <c>` + c*u16 —— 见 doc/ws2-byte-modality.md。
    name, end = _read_cstring(data, pos)
    _chk(_is_name(name), op_offset, 0x39, 'name bad')
    if end + 3 > len(data):
        raise UnknownInstruction(op_offset, 0x39, 'truncated')
    _chk(data[end] == 0x02 and data[end + 1] == 0x01, op_offset, 0x39,
         'params %s' % data[end:end + 5].hex())
    c = data[end + 2]
    _chk(1 <= c <= 64, op_offset, 0x39, 'frame count %d' % c)
    if end + 3 + 2 * c > len(data):
        raise UnknownInstruction(op_offset, 0x39, 'truncated frames')
    frames = [_u16(data, end + 3 + 2 * i) for i in range(c)]
    size = end + 3 + 2 * c - op_offset
    return size, data[pos + 1:end + 3 + 2 * c], {'name': _dec_str(name),
                                                 'count': c, 'frames': frames}

def _op_3f(data, pos, op_offset):
    # 3f LayersList <u8 count> <count x name NUL>   (LAYER_ORDER.ws2 的全部内容)
    if pos >= len(data):
        raise UnknownInstruction(op_offset, 0x3f, 'truncated')
    count = data[pos]
    p = pos + 1
    names = []
    for i in range(count):
        n, e = _read_cstring(data, p)
        _chk(_is_ascii(n) and len(n) > 0, op_offset, 0x3f, 'name %d bad' % i)
        names.append(_dec_str(n))
        p = e
    return p - op_offset, data[pos + 1:p], {'count': count, 'names': names}

def _op_45(data, pos, op_offset):
    # 45 DragBackground <通道 NUL> <u8 dragType> <u8 cfg> <f32 x> <f32 y> <f32 u> <f32 v>
    # 与 46 同为"图层变换"，区别是 45 带 2 个 u8 而 46 带 3 个。
    name, end = _read_cstring(data, pos)
    _chk(_is_name(name), op_offset, 0x45, 'name bad: %r' % name[:40])
    N = 18
    if end + N > len(data):
        raise UnknownInstruction(op_offset, 0x45, 'truncated')
    p = data[end:end + N]
    return end + N - op_offset, data[pos + 1:end + N], {
        'name': _dec_str(name),
        'v1': round(_f32(p, 2), 4), 'v2': round(_f32(p, 6), 4),
        'v3': round(_f32(p, 10), 4), 'v4': round(_f32(p, 14), 4), 'raw': p.hex()}

def _op_46(data, pos, op_offset):
    # 46 MoveBackground <通道 NUL> <u8 cfg0> <u8 cfg1> <u8 cfg2> <f32 x> <f32 y>
    #                  <f32 u> <f32 v>
    # **这条才是图层的位置**（通道名可以是 bg01，也可以是 st01..st12）。
    # 原点在屏幕中心、单位像素（同引擎的 `46 bg01 0 0 0 -640 -360 0 0` = 1280×720 左上角）；
    # 立绘 `y` 恒 -40。`cfg0 == 0x06` 是"重置"形态（四个 f32 为 10/11/12/13 占位值），
    # 只有 `cfg0 == 0x00` 的那条才是真实坐标 —— 见 doc/engine-mechanics.md。
    name, end = _read_cstring(data, pos)
    _chk(_is_name(name), op_offset, 0x46, 'name bad: %r' % name[:40])
    N = 19
    if end + N > len(data):
        raise UnknownInstruction(op_offset, 0x46, 'truncated')
    p = data[end:end + N]
    return end + N - op_offset, data[pos + 1:end + N], {
        'name': _dec_str(name), 'cfg': tuple(p[:3]),
        'x': round(_f32(p, 3), 4), 'y': round(_f32(p, 7), 4),
        'u': round(_f32(p, 11), 4), 'v': round(_f32(p, 15), 4), 'raw': p.hex()}

def _op_40(data, pos, op_offset):
    # 40 <slot NUL> [<file> NUL]
    #   第二个操作数只在它是**资源文件名**（如 `LAYERMASK_4001.PNG`）时存在：
    #   `40 "st03" 00 "LAYERMASK_4001.PNG" 00 00 46 ...`。
    #   本作语料里 0x40 还有 1-name 形态（ANIME_ERASE 系列：
    #   `40 "bg01_DELETE_ANIMEKEY" 00 6f 40 "bg01_DELETE_KEY" 00`，紧跟的是
    #   下一条 `6f 40 <key>`）。若不加区分地读第二个 name，会把它读成
    #   `o@bg01_DELETE_KEY`（都是可打印字节），从而吞掉下一条指令。
    #   判据：第二个 name 必须匹配资源文件名的字符集且含 '.'；否则退化为 1 name
    #   （与参照实现对 *_ANIME_ERASE.ws2 的读法逐字节一致）。
    n1, end1 = _read_cstring(data, pos)
    _chk(_is_name(n1) and len(n1) > 0, op_offset, 0x40, 'name1 bad: %r' % n1[:40])
    fields = {'name': _dec_str(n1)}
    if end1 < len(data) and data[end1] != 0x00:
        n2, end2 = _read_cstring(data, end1, limit=64)
        if _is_resource_name(n2):
            fields['name2'] = _dec_str(n2)
            return end2 - op_offset, data[pos + 1:end2], fields
    return end1 - op_offset, data[pos + 1:end1], fields

def _op_43(data, pos, op_offset):
    # 43 <slot NUL>   (本作新增；与 37 ClearLayer 同形)
    name, end = _read_cstring(data, pos)
    _chk(_is_name(name) and len(name) > 0, op_offset, 0x43, 'name bad: %r' % name[:40])
    return end - op_offset, data[pos + 1:end], {'name': _dec_str(name)}

# 19 -> 1 字节（无操作数），见 HANDLERS。

def _op_42(data, pos, op_offset):
    # 42 <slot NUL> <u16>   (本作新增；参照语料无此 opcode)
    #   形如 `42 "bg01" 00 02 00` / `42 "st05" 00 15 00`，u16 取值 1..0x60。
    name, end = _read_cstring(data, pos)
    _chk(_is_name(name) and len(name) > 0, op_offset, 0x42, 'name bad: %r' % name[:40])
    if end + 2 > len(data):
        raise UnknownInstruction(op_offset, 0x42, 'truncated')
    return end + 2 - op_offset, data[pos + 1:end + 2], {'name': _dec_str(name),
                                                       'value': _u16(data, end)}

def _op_74(data, pos, op_offset):
    # 74 <slot NUL> <u16>   (本作新增；参照语料无此 opcode)
    #   形如 `74 "timer01" 00 01 00`，与 11/12 同族（定时器槽名）。
    name, end = _read_cstring(data, pos)
    _chk(_is_name(name) and len(name) > 0, op_offset, 0x74, 'name bad: %r' % name[:40])
    if end + 2 > len(data):
        raise UnknownInstruction(op_offset, 0x74, 'truncated')
    return end + 2 - op_offset, data[pos + 1:end + 2], {'name': _dec_str(name),
                                                       'value': _u16(data, end)}

def _op_56(data, pos, op_offset):
    # 56 RainStart
    #   <name1 NUL> <u8 a> <u16 b> <u32 c> <10 x f32>
    #   <u8 f0 in {0,1}> <4 x f32> <u8 1> <u16 d>
    #   <name2 NUL> <u16 0> <name3 NUL> [<name4 NUL> ...] <nops>
    #   本作独有（参照语料 0 例）。全语料 19 例、6 个文件，逐字节模态完全一致
    #   （见 doc/ws2-byte-modality.md）。尾部的 name 列表长度可变：实测 2 个名字
    #   （`picture00`, `picture00`）或 3 个（多一个 `SYS_SNOW.PNG`）。判据：
    #   头部 64 字节固定，之后是 `<u8 1> <u16> <name2 NUL> <u16> `，再往后
    #   只要下一个字节是可打印 ASCII 就继续读一个 name；名字列表结束后必须
    #   紧跟 0x00（语料里是 4~6 个 nop，随后是 65/15/11/2e 等下一条指令）。
    #   **边界已定、语义未定**。
    name, end = _read_cstring(data, pos)
    _chk(_is_ascii(name) and len(name) > 0, op_offset, 0x56,
         'name bad: %r' % name[:40])
    if end + 64 > len(data):
        raise UnknownInstruction(op_offset, 0x56, 'truncated head')
    _chk(data[end + 47] in (0x00, 0x01), op_offset, 0x56,
         'marker1 0x%02x' % data[end + 47])
    _chk(data[end + 64] == 0x01, op_offset, 0x56,
         'marker2 0x%02x' % data[end + 64])
    n2, end2 = _read_cstring(data, end + 67)
    _chk(_is_ascii(n2) and len(n2) > 0, op_offset, 0x56, 'name2 bad')
    _chk(data[end2:end2 + 2] == b'\x00\x00', op_offset, 0x56,
         'name2 sep %s' % data[end2:end2 + 2].hex())
    p = end2 + 2
    names = []
    while p < len(data) and 0x20 <= data[p] < 0x7f:
        nm, e = _read_cstring(data, p, limit=64)
        _chk(len(nm) > 0, op_offset, 0x56, 'empty trailing name')
        names.append(_dec_str(nm))
        p = e
    _chk(bool(names) and data[p] == 0x00, op_offset, 0x56,
         'name list not terminated by NUL')
    # 收尾字段：实测 4~5 字节，除末 2 字节可能是 `80 3f`（某个正 f32 的高半部，
    # 如 1.0 = 00 00 80 3f）外全是 0x00。**边界已定、语义未定**。
    q = p
    while q < len(data) and data[q] == 0x00:
        q += 1
    trailing = q - p
    if trailing >= 3 and q + 2 <= len(data) and data[q:q + 2] == b'\x80\x3f':
        q += 2
        trailing += 2
    _chk(trailing in (4, 5), op_offset, 0x56, 'trailing %d' % trailing)
    return q - op_offset, data[pos + 1:q], {
        'name': _dec_str(name), 'a': data[end], 'n': _u16(data, end + 1),
        'name2': _dec_str(n2), 'names': names,
        'params': ' '.join('%.4f' % _f32(data, end + 7 + 4 * i)
                           for i in range(10))}

def _op_0f(data, pos, op_offset):
    # 0f <u8 count> count x (<u16 strid> <text NUL> 00 <u16 label> <jump>)
    if pos >= len(data):
        raise UnknownInstruction(op_offset, 0x0f, 'truncated')
    count = data[pos]
    entries, p = _parse_choice_entries(data, op_offset, 0x0f, count, pos + 1)
    return p - op_offset, data[pos + 1:p], {'count': count, 'entries': entries}

def _op_20(data, pos, op_offset):
    # 20 <slot NUL> <f32> <u16>   (BGM volume/loop config)
    name, end = _read_cstring(data, pos)
    _chk(_is_name(name), op_offset, 0x20, 'name bad')
    if end + 6 > len(data):
        raise UnknownInstruction(op_offset, 0x20, 'truncated')
    val = _f32(data, end)
    w = _u16(data, end + 4)
    return end + 6 - op_offset, data[pos + 1:end + 6], {'name': _dec_str(name),
                                                        'value': round(val, 6), 'w': w}

def _op_8f(data, pos, op_offset):
    # 8f <voice channel NUL> <file NUL> <u8> <text NUL>  (voice + subtitle line)
    ch, end1 = _read_cstring(data, pos)
    _chk(_is_ascii(ch) and len(ch) > 0, op_offset, 0x8f, 'chan bad')
    fn, end2 = _read_cstring(data, end1)
    _chk(_is_ascii(fn) and len(fn) > 0, op_offset, 0x8f, 'file bad')
    if end2 + 1 > len(data):
        raise UnknownInstruction(op_offset, 0x8f, 'truncated')
    a = data[end2]
    text, end3 = _read_cstring(data, end2 + 1)
    size = end3 - op_offset
    return size, data[pos + 1:end3], {'chan': _dec_str(ch), 'file': _dec_str(fn),
                                      'a': a, 'text': _dec_str(text)}

def _op_44(data, pos, op_offset):
    # 44 <name1 NUL> <name2 NUL> <u8>
    n1, end1 = _read_cstring(data, pos)
    _chk(_is_ascii(n1), op_offset, 0x44, 'name1 bad')
    n2, end2 = _read_cstring(data, end1)
    _chk(_is_ascii(n2), op_offset, 0x44, 'name2 bad')
    if end2 + 1 > len(data):
        raise UnknownInstruction(op_offset, 0x44, 'truncated')
    a = data[end2]
    return end2 + 1 - op_offset, data[pos + 1:end2 + 1], {'name': _dec_str(n1),
                                                          'name2': _dec_str(n2), 'a': a}

def _op_58(data, pos, op_offset):
    # 58 Effect3 <通道 NUL> <特效名 NUL> <7 raw bytes>
    n1, end1 = _read_cstring(data, pos)
    _chk(_is_ascii(n1), op_offset, 0x58, 'name1 bad')
    n2, end2 = _read_cstring(data, end1)
    _chk(_is_ascii(n2), op_offset, 0x58, 'name2 bad')
    if end2 + 7 > len(data):
        raise UnknownInstruction(op_offset, 0x58, 'truncated')
    tail = data[end2:end2 + 7]
    return end2 + 7 - op_offset, data[pos + 1:end2 + 7], {'name': _dec_str(n1),
                                                          'name2': _dec_str(n2),
                                                          'tail': tail.hex()}

def _op_66(data, pos, op_offset):
    # 66 ShowGraphic <名 NUL> 65 <u8 tag> 00 00 <f32> <u32 0> [<u16 2>]   (遮罩)
    name, end = _read_cstring(data, pos)
    _chk(_is_name(name), op_offset, 0x66, 'name bad: %r' % name[:40])
    N = 12
    if end + N > len(data):
        raise UnknownInstruction(op_offset, 0x66, 'truncated')
    p = data[end:end + N]
    _chk(p[0] == 0x65 and p[2:4] == b'\x00\x00' and p[8:12] == b'\x00' * 4,
         op_offset, 0x66, 'params %s' % p.hex())
    extra = 0
    if end + N + 2 <= len(data) and data[end + N:end + N + 2] == b'\x02\x00':
        extra = 2
    return end + N + extra - op_offset, data[pos + 1:end + N + extra], {
        'name': _dec_str(name), 'tag': p[1], 'value': round(_f32(p, 4), 4),
        'mode2': bool(extra)}

def _op_47(data, pos, op_offset):
    # 47 Effect1 <通道 NUL> <特效名 NUL> <u8×4> <f32×6> <u8×2>   (30B)
    #    [0..3] flags, f32 v1@4, f32 v2@8, 8x0@12, f32 v3@20, u32 0@24, u16 w@28
    n1, end1 = _read_cstring(data, pos)
    _chk(_is_ascii(n1), op_offset, 0x47, 'name1 bad: %r' % n1[:40])
    n2, end2 = _read_cstring(data, end1)
    _chk(_is_ascii(n2), op_offset, 0x47, 'name2 bad: %r' % n2[:40])
    N = 30
    if end2 + N > len(data):
        raise UnknownInstruction(op_offset, 0x47, 'truncated')
    p = data[end2:end2 + N]
    return end2 + N - op_offset, data[pos + 1:end2 + N], {
        'name': _dec_str(n1), 'name2': _dec_str(n2), 'head': p[0:4].hex(),
        'v1': round(_f32(p, 4), 4), 'v2': round(_f32(p, 8), 4),
        'v3': round(_f32(p, 20), 6), 'v4': round(_f32(p, 24), 6),
        'raw': p.hex()}

def _op_48(data, pos, op_offset):
    # 48 Effect2 <通道 NUL> <特效名 NUL> <u8×5>
    #    注意：这是 **WS2** 的 48，与 WSC 的 48（立绘显示）完全无关。
    n1, end1 = _read_cstring(data, pos)
    _chk(_is_ascii(n1), op_offset, 0x48, 'name1 bad')
    n2, end2 = _read_cstring(data, end1)
    _chk(_is_ascii(n2), op_offset, 0x48, 'name2 bad')
    if end2 + 5 > len(data):
        raise UnknownInstruction(op_offset, 0x48, 'truncated')
    a = data[end2 + 4]
    fields = {'name': _dec_str(n1), 'name2': _dec_str(n2),
              'u32': _u32(data, end2), 'a': a}
    end3 = end2 + 5
    if a == 0x02:
        n3, end3 = _read_cstring(data, end2 + 5)
        _chk(_is_ascii(n3), op_offset, 0x48, 'name3 bad')
        fields['name3'] = _dec_str(n3)
    return end3 - op_offset, data[pos + 1:end3], fields

def _op_51(data, pos, op_offset):
    # 51 40 <param slot NUL> <key slot NUL> <u8 idx> <u8 flag> <f32> <u8 0>
    _chk(data[pos] == 0x40, op_offset, 0x51, 'sub 0x%02x' % data[pos])
    n1, end1 = _read_cstring(data, pos + 1)
    _chk(_is_name(n1), op_offset, 0x51, 'name bad')
    n2, end2 = _read_cstring(data, end1)
    _chk(_is_name(n2), op_offset, 0x51, 'name2 bad')
    if end2 + 7 > len(data):
        raise UnknownInstruction(op_offset, 0x51, 'truncated keyframe')
    idx = data[end2]
    flg = data[end2 + 1]
    val = _f32(data, end2 + 2)
    z = data[end2 + 6]
    _chk(z == 0, op_offset, 0x51, 'kf trailer 0x%02x' % z)
    size = end2 + 7 - op_offset
    return size, data[pos + 1:end2 + 7], {'param': _dec_str(n1), 'key': _dec_str(n2),
                                          'idx': idx, 'flag': flg,
                                          'value': round(val, 6)}

def _op_52(data, pos, op_offset):
    # 52 <key slot NUL> 40 <param slot NUL> <f32> <u32 0> <u8 0>
    n1, end1 = _read_cstring(data, pos)
    _chk(_is_name(n1), op_offset, 0x52, 'name bad')
    _chk(end1 < len(data) and data[end1] == 0x40, op_offset, 0x52,
         'sub 0x%02x' % (data[end1] if end1 < len(data) else -1))
    n2, end2 = _read_cstring(data, end1 + 1)
    _chk(_is_name(n2), op_offset, 0x52, 'name2 bad')
    if end2 + 6 > len(data):
        raise UnknownInstruction(op_offset, 0x52, 'truncated')
    val = _f32(data, end2)
    # 本作形态：<f32> <u16 w> <u32 0> <u8 x>（参照实现只读 f32+2B）。
    # w ∈ {0x0000, 0xffff}；x 实测取 0/2，语义未定。尾部 6 字节的 0 是恒定的。
    if end2 + 11 > len(data):
        raise UnknownInstruction(op_offset, 0x52, 'truncated')
    w = _u16(data, end2 + 4)
    u = _u32(data, end2 + 6)
    _chk(w in (0x0000, 0xffff) and u == 0, op_offset, 0x52,
         'tail %s' % data[end2 + 4:end2 + 11].hex())
    return end2 + 11 - op_offset, data[pos + 1:end2 + 11], {
        'key': _dec_str(n1), 'param': _dec_str(n2), 'value': round(val, 6),
        'w': w, 'x': data[end2 + 10]}

def _op_53(data, pos, op_offset):
    # 53 40 <name NUL>                 (anim: bind key, from *_ANIME_ERASE.ws2)
    # 53 <name NUL>                    (anim: trigger effect key；本作语料里
    #   名字后**没有**参照实现的那 2 字节——`53 "T07_ANIME_ERASE" 00 2e 28 ...`
    #   的 `2e 28` 已经是下一条语音播放指令)
    if data[pos] == 0x40:
        return _name_op(0x53, pre_bytes=1, ascii_only=True)(data, pos, op_offset)
    return _name_op(0x53, ascii_only=True)(data, pos, op_offset)

def _op_65(data, pos, op_offset):
    # 65 <u8 a> <u8 0> <u8 0> <f32> <u32 0> <u16 mode>   (fade; a=0 or 0x64,
    #                                                     mode 0/1/2)
    if pos + 13 > len(data):
        raise UnknownInstruction(op_offset, 0x65, 'truncated')
    p = data[pos:pos + 13]
    # 本作变体：[2] 可为 0x01（如 `65 00 00 01 <f32> 0 0 0 0 mode`），[1] 恒 0。
    _chk(p[1] == 0x00 and p[7:11] == b'\x00' * 4, op_offset,
         0x65, 'params %s' % p.hex())
    return 14, p, {'a': p[0], 'b': p[2], 'value': round(_f32(p, 3), 6),
                   'f32hex': p[3:7].hex(), 'mode': _u16(p, 11)}

def _op_67(data, pos, op_offset):
    # 67 <25 raw bytes>  (a,b flags + f32 v1@4 v2@8 v3@12)
    if pos + 25 > len(data):
        raise UnknownInstruction(op_offset, 0x67, 'truncated')
    p = data[pos:pos + 25]
    return 26, p, {'a': p[0], 'b': p[1], 'v1': round(_f32(p, 4), 4),
                   'v2': round(_f32(p, 8), 4), 'v3': round(_f32(p, 12), 4), 'raw': p.hex()}

def _op_ff(data, pos, op_offset):
    # ff <u32 a> <u32 b>   (END of script; a: 0=menu/title, 4/0xc4=title return,
    #                       8=scene-jump load; b: 128 when script has choices)
    if pos + 8 > len(data):
        raise UnknownInstruction(op_offset, 0xff, 'truncated')
    a = _u32(data, pos)
    b = _u32(data, pos + 4)
    return 9, data[pos:pos + 8], {'a': a, 'b': b}

def _op_c9(data, pos, op_offset):
    # c9 <layer NUL> <voice-char NUL> <6 bytes>  (voice/layer mapping)
    return _two_name_op(0xc9, extra=6)(data, pos, op_offset)

# opcode -> handler
HANDLERS = {
    0x00: lambda d, p, o: (1, b'', {}),                      # nop / label marker
    0x01: _op_01,
    0x02: _fixed(4, ('a', 'u32', 0)),                        # set next-script index?
    0x03: lambda d, p, o: _op_05(d, p, o),                   # 03 <u8> <u32> <u32> (SE stop)
    0x04: _op_04,
    0x05: _op_05,
    0x06: _op_06,
    0x07: _op_07,
    0x08: _fixed(1, ('a', 'u8', 0)),                         # checkpoint? (mainmenu)
    0x09: _op_09,
    0x0a: _fixed(6, ('a', 'u8', 0), ('b', 'u32', 1), ('c', 'u8', 5)),
    0x0b: _fixed(3, ('id', 'u16', 0), ('a', 'u8', 2)),
    0x0e: _op_0e,
    0x0f: _op_0f,
    0x11: _op_11,
    0x12: _op_12,
    0x13: _fixed(9, ('a', 'u8', 0)),                         # 13 ff 00*8 seen
    0x14: _op_14,
    0x15: _op_15,
    0x16: _fixed(2, ('a', 'u8', 0), ('b', 'u8', 1)),
    0x18: _fixed(1, ('a', 'u8', 0)),
    0x1a: _name_op(0x1a, ascii_only=True),                   # Lua call, no args
    0x1b: _fixed(1, ('a', 'u8', 0)),
    0x1c: lambda d, p, o: (_name_op(0x1c, extra=4, ascii_only=True) if p < len(d) and d[p] == 0
                           else _two_name_op(0x1c, extra=3, ascii_only=True))(d, p, o),
    0x19: lambda d, p, o: (1, b'', {}),
    0x1d: _fixed(2, ('a', 'u16', 0)),
    0x1e: _op_1e,
    0x1f: _op_1f,
    0x20: _op_20,                                            # BGM volume/loop config
    0x28: _op_28,
    0x29: _op_29,
    0x2a: _op_20,   # 2a <slot NUL> <f32> <u16>
    0x2e: _op_2e,
    0x32: _fixed(5, ('raw', 5, 0)),                          # menu click sfx? const 0068011771
    0x33: _op_33,
    0x34: _op_34,
    0x35: _op_35,
    0x37: _name_op(0x37, ascii_only=True),                   # anim stop on slot ('*'=all)
    0x38: lambda d, p, o: (_name_op(0x38, extra=1, pre_bytes=1, ascii_only=True) if d[p] == 0x40
                           else (_ for _ in ()).throw(UnknownInstruction(o, 0x38, 'sub 0x%02x' % d[p])))(d, p, o),
    0x39: _op_39,
    0x3a: lambda d, p, o: _name_op(0x3a, extra=2, ascii_only=True)(d, p, o),  # movie stop
    0x3d: _fixed(2, ('a', 'u16', 0)),
    0x3e: lambda d, p, o: (1, b'', {}),
    0x3f: _op_3f,
    0x40: _op_40,
    0x41: lambda d, p, o: _name_op(0x41, ascii_only=False)(d, p, o),  # <slot NUL>
    0x42: _op_42,
    0x43: _op_43,
    0x44: _op_44,
    0x45: _op_45,
    0x46: _op_46,
    0x47: _op_47,
    0x48: _op_48,
    0x4a: _two_name_op(0x4a, ascii_only=False),   # 4a <slot NUL> <effect NUL>
    0x51: _op_51,
    0x52: _op_52,
    0x53: _op_53,
    0x55: _two_name_op(0x55, extra=2, ascii_only=True),      # remove sprite (TOREMOVE)
    0x56: _op_56,
    0x57: lambda d, p, o: _name_op(0x57, extra=2, ascii_only=True)(d, p, o),
    0x58: _op_58,
    0x5c: lambda d, p, o: _name_op(0x5c, ascii_only=False)(d, p, o),  # RainEnd <name>
    0x64: _fixed(1, ('a', 'u8', 0)),
    0x65: _op_65,
    0x66: _op_66,
    0x67: _op_67,
    0x68: _fixed(1, ('a', 'u8', 0)),                         # sound-related prelude
    0x6e: lambda d, p, o: (_two_name_op(0x6e, pre_bytes=1, ascii_only=True) if d[p] == 0x40
                           else (_ for _ in ()).throw(UnknownInstruction(o, 0x6e, 'sub 0x%02x' % d[p])))(d, p, o),
    0x6f: lambda d, p, o: (_name_op(0x6f, pre_bytes=1, ascii_only=True) if d[p] == 0x40
                           else (_ for _ in ()).throw(UnknownInstruction(o, 0x6f, 'sub 0x%02x' % d[p])))(d, p, o),
    0x74: _op_74,
    0x8f: _op_8f,
    0xc9: _op_c9,
    0xf0: _fixed(1, ('a', 'u8', 0)),
    0xfb: _fixed(1, ('a', 'u8', 0)),
    0xfc: _fixed(1, ('a', 'u8', 0)),
    0xfd: lambda d, p, o: (1, b'', {}),
    0xff: _op_ff,
}

def _disassemble(data):
    out = []
    pos = 0
    n = len(data)
    while pos < n:
        op = data[pos]
        h = HANDLERS.get(op)
        if h is None:
            raise UnknownInstruction(pos, op)
        size, _operands, fields = h(data, pos + 1, pos)
        if size <= 0 or pos + size > n:
            raise UnknownInstruction(pos, op, 'bad size %d' % size)
        # 统一 operands 约定：恒等于 data[offset+1 : offset+size]（原始操作数字节）。
        # 参照实现的各 handler 对 operands 的切片起点不一致（有的少 1 字节），
        # 这里在出口处归一化，保证 size == len(operands) + 1 永远成立。
        out.append(Instruction(pos, op, size, data[pos + 1:pos + size], fields))
        pos += size
    return out


def disassemble(data, sep11=None):
    """Linearly disassemble a decoded WS2 script. Returns list[Instruction].
    Raises UnknownInstruction if the whole file cannot be tiled.

    `sep11` selects the opcode-0x11 encoding: True = `11 <name>\\0 00 <f32>`
    (Steam/backup corpus), False = `11 <name>\\0 <f32>` (2015 original corpus).
    None (default) auto-detects per instruction and, if the file still does not
    tile, retries the whole file with the other default."""
    global _SEP11_DEFAULT
    modes = (sep11,) if sep11 is not None else (True, False)
    last = None
    for m in modes:
        _SEP11_DEFAULT[0] = m
        try:
            return _disassemble(data)
        except UnknownInstruction as exc:
            last = exc
    _SEP11_DEFAULT[0] = True
    raise last
