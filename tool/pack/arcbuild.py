"""ARC reader/writer that preserves member names byte-exactly.

The earlier build scripts round-tripped members through the filesystem, which
mangled the Japanese UTF-16LE names in Graphic.arc, and wrote *absolute* data
offsets even though read_arc (and the engine) treat the offset field as
relative to 8 + table_size. Both bugs are avoided here by carrying raw name
bytes and computing relative offsets.
"""
import struct
from pathlib import Path

HEADER = struct.Struct('<II')
ENTRY = struct.Struct('<II')


def read_raw(path):
    """Return [(name_bytes, data)] with names exactly as stored on disk."""
    blob = Path(path).read_bytes()
    count, table_size = HEADER.unpack_from(blob, 0)
    data_start = 8 + table_size
    out = []
    off = 8
    for _ in range(count):
        size, rel = ENTRY.unpack_from(blob, off)
        off += 8
        start = off
        while blob[off:off + 2] != b'\0\0':
            off += 2
        name_bytes = blob[start:off]
        off += 2
        begin = data_start + rel
        data = blob[begin:begin + size]
        if len(data) != size:
            raise ValueError('truncated member %r in %s' % (name_bytes, path))
        out.append((name_bytes, data))
    return out


def write_arc(members, output_path):
    """Write members as [(name_bytes, data)]; offsets are relative."""
    table_size = sum(8 + len(n) + 2 for n, _ in members)
    table = bytearray()
    rel = 0
    for name_bytes, data in members:
        table += ENTRY.pack(len(data), rel)
        table += name_bytes + b'\0\0'
        rel += len(data)
    if len(table) != table_size:
        raise AssertionError('table size mismatch')

    with open(output_path, 'wb') as fh:
        fh.write(HEADER.pack(len(members), table_size))
        fh.write(table)
        for _, data in members:
            fh.write(data)
    return Path(output_path).stat().st_size


def verify(path, expect_count=None):
    """Re-read an archive and assert every member lies inside the file."""
    blob = Path(path).read_bytes()
    count, table_size = HEADER.unpack_from(blob, 0)
    data_start = 8 + table_size
    off, seen, end = 8, 0, data_start
    for _ in range(count):
        size, rel = ENTRY.unpack_from(blob, off)
        off += 8
        while blob[off:off + 2] != b'\0\0':
            off += 2
        off += 2
        stop = data_start + rel + size
        if stop > len(blob):
            raise ValueError('member overruns file: %d > %d' % (stop, len(blob)))
        end = max(end, stop)
        seen += 1
    if seen != count:
        raise ValueError('entry count mismatch')
    if expect_count is not None and count != expect_count:
        raise ValueError('expected %d members, got %d' % (expect_count, count))
    return count, len(blob), end
