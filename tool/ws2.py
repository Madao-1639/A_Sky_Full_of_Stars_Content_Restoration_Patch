"""ASFoS .ws2 script codec and achievement-call injection.

Obfuscation is a per-byte rotate-left-6 (verified: round-trips byte-exactly,
and exposes ASCII opcode operands such as script names and CG filenames).

Relevant opcodes (operand forms confirmed against all 277 Steam story scripts):

    0x34  <slot>\0 <FILE.PNA>\0 0x01 0x01     display a CG into a layer slot
    0x0b  <u16 var> 0x01                      push/set a variable
    0x04  <NAME>\0                            call another script by name

A CG display is always followed by two 0x0b variable-set ops carrying the CG's
gallery id and differential id. Those two ops exist in BOTH the Steam and the
original scripts -- they are intrinsic to displaying a CG, not part of the
achievement feature. Byte-diffing the same scene in both versions shows the
Steam build adds exactly 16 bytes:

    ...0101  0b <u16 A> 04 01  0b <u16 B> 04 01  [04 "CG_ACHIEVEMENT" 00]  39...
             |<------- present in both versions ------->|  |<- Steam only ->|

So injection means inserting only the 16-byte call after the existing variable
pair -- never re-emitting the pair, whose operands must be left untouched.
"""
import re
import struct

ACH_NAME = b'CG_ACHIEVEMENT'
ACH_CALL = b'\x04' + ACH_NAME + b'\x00'

# 0x34 <slot> 00 <STEM>.PNA 00 01 01 followed by the intrinsic id pair.
# Each set op is four bytes: 0b <u16 le> 01  (e.g. 0b 60 04 01 -> var 1120).
DISPLAY = re.compile(
    rb'\x34([A-Za-z0-9_]{2,12})\x00([A-Za-z0-9_]+)\.PNA\x00\x01\x01'
    rb'\x0b(..)\x01\x0b(..)\x01', re.S)
SIZE_SUFFIX = re.compile(r'[LSMWX]$')


def decode(raw):
    """Deobfuscate a .ws2 member (rotate left 6)."""
    return bytes(((c << 6) | (c >> 2)) & 0xff for c in raw)


def encode(data):
    """Re-obfuscate a .ws2 member (inverse: rotate right 6 == left 2)."""
    return bytes(((c << 2) | (c >> 6)) & 0xff for c in data)


def cg_base(stem):
    """COM_04L -> COM_04 (strip the size-variant suffix)."""
    return SIZE_SUFFIX.sub('', stem)


def read_id_map(members):
    """Extract {cg_base: (A, {B...})} from the intrinsic id pair of each display.

    Read from the original scripts as readily as from Steam's: the pair is
    present in both, so no achievement ids ever need to be invented.
    """
    a_of = {}
    b_of = {}
    for name, raw in members:
        data = decode(raw)
        for m in DISPLAY.finditer(data):
            base = cg_base(m.group(2).decode('ascii'))
            a_of[base] = struct.unpack('<H', m.group(3))[0]
            b_of.setdefault(base, set()).add(
                struct.unpack('<H', m.group(4))[0])
    return a_of, b_of


def find_display_sites(data):
    """Yield (end_offset, cg_base, has_call) for every CG display op.

    end_offset points just past the intrinsic id pair, which is exactly where
    the achievement call belongs.
    """
    for m in DISPLAY.finditer(data):
        has_call = data[m.end():m.end() + len(ACH_CALL)] == ACH_CALL
        yield m.end(), cg_base(m.group(2).decode('ascii')), has_call


def inject(raw):
    """Insert the achievement call after every CG display that lacks one.

    Returns (new_raw, injected_count). Only the 16-byte call is spliced in; the
    intrinsic id pair already present in the script is left byte-for-byte
    intact, so the CG's own ids are reused rather than recomputed. The format
    has no absolute jump table (Steam's own scene scripts differ in length while
    sharing identical encodings), so splicing is safe.
    """
    data = decode(raw)
    out = bytearray()
    cursor = 0
    injected = 0
    for end, _base, has_call in find_display_sites(data):
        if has_call:
            continue
        out += data[cursor:end]
        out += ACH_CALL
        cursor = end
        injected += 1
    out += data[cursor:]
    return encode(bytes(out)), injected
