"""CHT exe (miagete_cht_170416.exe) overlay cipher - offline reference implementation.

Recovered by static analysis of the on-disk stub (fake .text) and verified
against ground truth by a mini x86 interpreter (tmp/interp.py) and the live
process (x32dbg). All multi-byte fields little-endian.

LAYOUT OF THE EXE
  0x00000000  PE image (decoy): .text ~60KB obfuscated unpacker, .data 16KB
  0x00048000  overlay start (= end of last PE section .rsrc)
    0x48000..0x48008   magic, u32[0] ^ u32[1] == 0x1F040E15
    0x48008..0x481F8   496-byte header, CBC-encrypted (see below)
                       plaintext: +0  = 0x0011DBFD
                                  +8  = 0x000481F8 (header end / file offset)
                                  +32 = blob offset, +36 = blob size, +44 = end
                                  +368..383 = key blob (stored ENCRYPTED)
    0x48338..0x87AB0   module blob: [u32 uncompressed_size][LZSS stream]
    0x87AB0..EOF       engine container: descriptor + section table
                       (.text/.rdata/.data blobs, .rsrc reused from stub)

CIPHER
  S-box (256 bytes), built once:
      sbox[i] = LOBYTE(dword_4120D0[i]) ^ LOBYTE(0x22043E6F >> ((i+1) % 31))
  Key material (60 bytes) from a 15-byte blob via the mod-15 permutation
  sub_404371 (see perm15 below). Starting state i=11.
  Block function sub_402425 (8 rounds, round r uses key bytes [7r..7r+6],
  then a 4-byte tail using key bytes [56..59]):
      v=b[3]^k[3]; b[7]^=sbox[v]      v=b[0]^k[0]; b[4]^=sbox[v]
      v=b[2]^k[2]; b[6]^=sbox[v]      v=b[1]^k[1]; b[5]^=sbox[v]
      v=b[4]^k[4]; b[1]^=sbox[v]      v=b[4]^b[5]; b[2]^=sbox[v]
      v=b[6]^k[5]; b[3]^=sbox[v]      v=b[7]^k[6]; b[0]^=sbox[v]
      tail: for j in 0..3: b[j+4] ^= sbox[b[j] ^ km[56+j]]
  The two "ops" sub_4053D9/sub_405991 are both plain XOR (constant-obfuscated).
  Bulk mode sub_40540E = CBC with ciphertext feedback: P_i = D(C_i) ^ C_{i-1},
  IV = 0. The string decryptor sub_40163F uses plain ECB per 8-byte block,
  stopping at the first NUL.

LZSS (sub_4060CC)
  b == 0x80        : literal next byte
  b == 0x00        : literal run, count = next byte + 1
  else (2 bytes w) : back-ref, distance = (w >> 4) + 15, length = w & 0xF
"""
import struct

CONST = 0x22043E6F


def load_sbox(exe_bytes):
    tbl_off = 0x120D0  # VA 0x4120D0 (file .data raw)
    dwords = struct.unpack_from('<256I', exe_bytes, tbl_off)
    return bytearray((dwords[i] & 0xFF) ^ ((CONST >> ((i + 1) % 31)) & 0xFF)
                     for i in range(256))


def perm15(blob):
    """sub_404371: 60-byte key material from a 15-byte blob."""
    key = bytearray(64)
    p = 0
    i = 11
    while True:
        key[p + 0] = blob[i % 15]
        key[p + 1] = blob[(i + 1) % 15]
        key[p + 2] = blob[(i + 2) % 15]
        key[p + 3] = blob[(i + 3) % 15]
        v7 = ((i + 3) % 15 + 9) % 15
        if v7 == 12:
            break
        key[p + 4] = blob[v7]
        key[p + 5] = blob[(v7 + 1) % 15]
        key[p + 6] = blob[(v7 + 2) % 15]
        p += 7
        i = (v7 + 2 + 9) % 15
    return bytes(key[:p + 4])


def make_block_dec(sbox, keymat):
    def block_dec(b):
        for r in range(8):
            k = keymat[7 * r:7 * r + 7]
            v = b[3] ^ k[3]; b[7] ^= sbox[v]
            v = b[0] ^ k[0]; b[4] ^= sbox[v]
            v = b[2] ^ k[2]; b[6] ^= sbox[v]
            v = b[1] ^ k[1]; b[5] ^= sbox[v]
            v = b[4] ^ k[4]; b[1] ^= sbox[v]
            v = b[4] ^ b[5]; b[2] ^= sbox[v]
            v = b[6] ^ k[5]; b[3] ^= sbox[v]
            v = b[7] ^ k[6]; b[0] ^= sbox[v]
        for j in range(4):
            v = b[j] ^ keymat[56 + j]
            b[j + 4] ^= sbox[v]
    return block_dec


def cbc_decrypt(sbox, keymat, buf):
    block_dec = make_block_dec(sbox, keymat)
    out = bytearray()
    prev = bytearray(8)
    for i in range(0, len(buf) - len(buf) % 8, 8):
        c = bytearray(buf[i:i + 8])
        b = bytearray(c)
        block_dec(b)
        out += bytes(x ^ y for x, y in zip(b, prev))
        prev = c
    return bytes(out)


def lzss_decompress(src, dstlen):
    out = bytearray()
    i = 0
    n = len(src)
    while i < n and len(out) < dstlen:
        b = src[i]
        if b == 0x80:
            out.append(src[i + 1]); i += 2
        elif b != 0:
            w = struct.unpack_from('<H', src, i)[0]
            dist = (w >> 4) + 15
            ln = w & 0xF
            start = len(out) - dist
            for k in range(ln):
                out.append(out[start + k])
            i += 2
        else:
            cnt = src[i + 1] + 1
            out += src[i + 2:i + 2 + cnt]; i += 2 + cnt
    return bytes(out)
