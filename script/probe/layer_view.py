"""PNA 逐层对照：打印每层元数据/可读性/是否像素不同，并导出指定层的左右对照缩略图。

用法: python script/probe/layer_view.py <archive> <member.pna> [--layer N] [--out PATH]
"""
import argparse
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tool import arcbuild, pna

JP = ROOT.parent / '抬头看看吧看那天上的繁星'
ASSET = ROOT / 'asset'


def get(base, archive, name):
    for nb, d in arcbuild.read_raw(base / archive):
        if nb.decode('utf-16le').upper() == name.upper():
            return d
    raise SystemExit('未找到 %s/%s' % (base.name, name))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('archive')
    ap.add_argument('member')
    ap.add_argument('--layer', type=int)
    ap.add_argument('--out')
    ap.add_argument('--width', type=int, default=760)
    a = ap.parse_args()
    from PIL import Image, ImageChops, ImageDraw

    pr = pna.load(get(JP, a.archive, a.member))
    pa = pna.load(get(ASSET, a.archive, a.member))
    print('canvas %sx%s 层数 %s / %sx%s 层数 %s'
          % (pr['canvas_w'], pr['canvas_h'], pr['layer_count'],
             pa['canvas_w'], pa['canvas_h'], pa['layer_count']))
    print('%-4s %-5s %-24s %-16s %-16s %s' % ('idx', 'lid', 'box(原版)', '原版img', 'Steam img', '差异'))
    diff_layers = []
    for i in range(min(len(pr['images']), len(pa['images']))):
        ia, ib = pr['images'][i], pa['images'][i]
        sa = sb = '—'
        note = ''
        iaim = ibim = None
        try:
            if ia is not None:
                iaim = Image.open(io.BytesIO(ia)).convert('RGBA')
                sa = '%dx%d' % iaim.size
        except Exception as e:
            sa = 'ERR(%s)' % type(e).__name__
        try:
            if ib is not None:
                ibim = Image.open(io.BytesIO(ib)).convert('RGBA')
                sb = '%dx%d' % ibim.size
        except Exception as e:
            sb = 'ERR(%s)' % type(e).__name__
        if iaim is not None and ibim is not None and iaim.size == ibim.size:
            d = ImageChops.difference(iaim, ibim).convert('L')
            bb = d.getbbox()
            peak = d.getextrema()[1]
            if bb:
                diff_layers.append(i)
                note = 'bbox=%s peak=%d' % (bb, peak)
        elif ia != ib:
            note = '尺寸/可读性不同'
        print('%-4d %-5s %-24s %-16s %-16s %s'
              % (i, pr['entries'][i][1], str(pr['entries'][i][2:6]), sa, sb, note))

    print('\n像素不同的层（0 基）：%s' % diff_layers)
    li = a.layer if a.layer is not None else (diff_layers[0] if diff_layers else 0)
    iaim = Image.open(io.BytesIO(pr['images'][li])).convert('RGBA')
    ibim = Image.open(io.BytesIO(pa['images'][li])).convert('RGBA')
    sc = min(1.0, a.width / iaim.width)
    ra = iaim.resize((max(1, int(iaim.width * sc)), max(1, int(iaim.height * sc))))
    rb = ibim.resize((max(1, int(ibim.width * sc)), max(1, int(ibim.height * sc))))
    d = ImageChops.difference(iaim, ibim).convert('L')
    bb = d.getbbox()
    if bb:
        c = iaim.crop(bb)
        z = max(1, min(6, 900 // max(1, c.width)))
        ca = c.resize((c.width * z, c.height * z), Image.NEAREST)
        cb = ibim.crop(bb).resize((c.width * z, c.height * z), Image.NEAREST)
    else:
        ca = cb = None
    W = max(ra.width + rb.width + 36, (ca.width + 36) if ca else 0)
    H = 250 + (ca.height + 40 if ca else 0) + 30
    out = Image.new('RGBA', (W, H), (24, 24, 28, 255))
    out.paste(ra, (12, 26), ra)
    out.paste(rb, (24 + ra.width, 26), rb)
    dr = ImageDraw.Draw(out)
    dr.text((12, 8), 'ref (原版) 层 %d' % li, fill=(255, 220, 120, 255))
    dr.text((24 + ra.width, 8), 'alt (Steam) 层 %d' % li, fill=(120, 220, 255, 255))
    y = 26 + ra.height + 12
    if ca:
        out.paste(ca, (12, y + 16), ca)
        out.paste(cb, (24 + ca.width, y + 16), cb)
        dr.text((12, y), '差异区 %s ×%d' % (str(bb), z), fill=(255, 120, 120, 255))
    path = a.out or str(ROOT / 'tmp' / ('layer_%s.png' % Path(a.member).stem))
    out.convert('RGB').save(path)
    print('已写出 %s' % path)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
