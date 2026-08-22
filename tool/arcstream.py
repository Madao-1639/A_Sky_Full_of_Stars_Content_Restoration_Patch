"""Streaming ARC helpers: list members without loading payloads, and rewrite
an archive by copying retained payloads straight from the source file.

Needed because Voice.arc/Voice1.arc are ~800MB and ~424MB; read_raw() would
hold the whole blob plus a second copy of every retained member in RAM.
Offsets follow arcbuild's convention: the entry field is relative to
8 + table_size.
"""
import struct

HEADER = struct.Struct('<II')
ENTRY = struct.Struct('<II')


def read_index(path):
    """Return (data_start, [(name_bytes, rel_offset, size)]) reading only the table."""
    with open(path, 'rb') as fh:
        count, table_size = HEADER.unpack(fh.read(8))
        table = fh.read(table_size)
    if len(table) != table_size:
        raise ValueError('truncated member table in %s' % path)
    out = []
    off = 0
    for _ in range(count):
        size, rel = ENTRY.unpack_from(table, off)
        off += 8
        start = off
        while table[off:off + 2] != b'\0\0':
            off += 2
        name_bytes = table[start:off]
        off += 2
        out.append((name_bytes, rel, size))
    return 8 + table_size, out


def names(path):
    """Return the member names as decoded UTF-16LE strings, in stored order."""
    _data_start, index = read_index(path)
    return [nb.decode('utf-16le') for nb, _rel, _sz in index]


def copy_subset(src_path, dst_path, keep_pred, chunk=1 << 22):
    """Write dst containing only members where keep_pred(name) is true.

    Payloads are streamed from src, so peak memory stays at one chunk.
    Returns (kept_count, kept_bytes, dropped) with dropped as [(name, size)].
    """
    data_start, index = read_index(src_path)
    kept, dropped = [], []
    for name_bytes, rel, size in index:
        name = name_bytes.decode('utf-16le')
        if keep_pred(name):
            kept.append((name_bytes, rel, size))
        else:
            dropped.append((name, size))

    table_size = sum(8 + len(nb) + 2 for nb, _r, _s in kept)
    table = bytearray()
    new_rel = 0
    for name_bytes, _rel, size in kept:
        table += ENTRY.pack(size, new_rel)
        table += name_bytes + b'\0\0'
        new_rel += size
    if len(table) != table_size:
        raise AssertionError('table size mismatch')

    with open(src_path, 'rb') as src, open(dst_path, 'wb') as dst:
        dst.write(HEADER.pack(len(kept), table_size))
        dst.write(table)
        for _nb, rel, size in kept:
            src.seek(data_start + rel)
            left = size
            while left:
                buf = src.read(min(chunk, left))
                if not buf:
                    raise ValueError('unexpected EOF in %s' % src_path)
                dst.write(buf)
                left -= len(buf)
    return len(kept), new_rel, dropped


def sha256_file(path, chunk=1 << 22):
    import hashlib
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        while True:
            buf = fh.read(chunk)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()
