"""PNAP (.pna) layer-container reader/writer.

Layout (all fields little-endian):
  header: magic b'PNAP', unknown(i32)=44*layer_count+12, canvas_w(i32), canvas_h(i32), layer_count(i32)
  layer_count x entry, 10 x i32 each:
    [0] u0        -- 0 for real layers; 1/2 for group-boundary sentinels (see doc/pna-resources.md)
    [1] layer_id  -- position-derived id used by 0x34 (layer_count-1-index); -1 for sentinels
    [2] box_x, [3] box_y, [4] box_w, [5] box_h  -- placement rect within the canvas
    [6] reserved  -- always 0 in observed samples
    [7],[8]       -- IEEE754 double 1.0 marker (low/high i32), zero for sentinels
    [9] size      -- byte length of this layer's embedded PNG; 0 for sentinels
  Layer PNGs follow the table back-to-back, in table order, for entries with size>0.

box_w/box_h always match the embedded PNG's own width/height (verified across every
non-sentinel layer in Chip3.arc's COM_04*/COM_05* members) -- this is a per-layer
placement rect, not tied to canvas_w/canvas_h.
"""
import struct

HEADER = struct.Struct('<4siiii')
ENTRY = struct.Struct('<iiiiiiiiii')


def load(data):
    magic, unknown, canvas_w, canvas_h, layer_count = HEADER.unpack_from(data, 0)
    if magic != b'PNAP':
        raise ValueError('not a PNAP file (magic=%r)' % magic)
    off = HEADER.size
    entries = []
    for _ in range(layer_count):
        entries.append(list(ENTRY.unpack_from(data, off)))
        off += ENTRY.size
    images = []
    for e in entries:
        size = e[9]
        if size > 0:
            images.append(data[off:off + size])
            off += size
        else:
            images.append(None)
    if off != len(data):
        raise ValueError('trailing %d bytes after last layer image' % (len(data) - off))
    return {
        'unknown': unknown,
        'canvas_w': canvas_w,
        'canvas_h': canvas_h,
        'layer_count': layer_count,
        'entries': entries,
        'images': images,
    }


def dump(p):
    out = bytearray()
    out += HEADER.pack(b'PNAP', p['unknown'], p['canvas_w'], p['canvas_h'], p['layer_count'])
    for e in p['entries']:
        out += ENTRY.pack(*e)
    for img in p['images']:
        if img is not None:
            out += img
    return bytes(out)


def find_by_layer_id(p, layer_id):
    """Return the table index whose stored layer_id matches and that has image data."""
    matches = [i for i, e in enumerate(p['entries'])
               if e[1] == layer_id and p['images'][i] is not None]
    if not matches:
        raise ValueError('layer_id %d not found (or has no image)' % layer_id)
    if len(matches) > 1:
        raise ValueError('layer_id %d is ambiguous: table indices %r' % (layer_id, matches))
    return matches[0]


def get_box(p, idx):
    return tuple(p['entries'][idx][2:6])


def replace_layer(p, layer_id, png_bytes, box):
    """Overwrite the image bytes and placement box for `layer_id` in place."""
    idx = find_by_layer_id(p, layer_id)
    e = p['entries'][idx]
    e[2], e[3], e[4], e[5] = box
    e[9] = len(png_bytes)
    p['images'][idx] = png_bytes
