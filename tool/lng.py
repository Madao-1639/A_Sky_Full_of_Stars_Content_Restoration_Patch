"""ASFoS .lng localization container codec.

Layout (verified byte-exact round-trip on all 311 zh-CN members):
    u32                 count
    u16 * count         per-string byte length (includes the trailing NUL pair)
    bytes               count strings, back-to-back, no padding

Each string is UTF-16LE XORed with 0xCE.
"""
import struct

XOR = 0xCE
_TAB = bytes(c ^ XOR for c in range(256))


def parse_lng(raw):
    """Return the list of decoded strings (trailing NUL stripped)."""
    count = struct.unpack_from('<I', raw, 0)[0]
    lens = struct.unpack_from('<%dH' % count, raw, 4)
    off = 4 + 2 * count
    if off + sum(lens) != len(raw):
        raise ValueError('lng length table does not cover payload')
    out = []
    for length in lens:
        chunk = raw[off:off + length]
        off += length
        out.append(chunk.translate(_TAB).decode('utf-16le').rstrip('\0'))
    return out


def encode_lng(strings):
    """Inverse of parse_lng."""
    blobs = [(s + '\0').encode('utf-16le').translate(_TAB) for s in strings]
    out = bytearray(struct.pack('<I', len(blobs)))
    for blob in blobs:
        if len(blob) > 0xffff:
            raise ValueError('string exceeds u16 length field')
        out += struct.pack('<H', len(blob))
    for blob in blobs:
        out += blob
    return bytes(out)
