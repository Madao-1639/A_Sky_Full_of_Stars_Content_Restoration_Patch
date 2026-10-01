"""把同名冲突的**差异区域**两侧裁剪对照图导出（PNG 整图 / PNA 指定层），供人工读图。

差异区自动定位（α 掩膜 + 通道差阈值），把 ref（原版）/ alt（Steam）在该区域各裁一块、
放大 --zoom 倍、左右并排，输出一张 PNG。

用法:
  python script/probe/crop_diff.py <archive> <member> [--layer N] [--out PATH] [--zoom 4]
  # ref = ../抬头看看吧看那天上的繁星/<archive>，alt = asset/<archive>
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


def member(archive, name):
    for base in (JP, ASSET):
        for nb, d in arcbuild.read_raw(base / archive):
            if nb.decode('utf-16le').upper() == name.upper():
                return d
    raise SystemExit('未找到 %s:%s' % (archive, name))


def diff_box(ia, ib, over=8):
    from PIL import ImageChops
    a = ia.convert('RGBA')
    b = ib.convert('RGBA')
    mask = ImageChops.difference(a, b)
    # α 掩膜：仅统计两侧都不透明的像素
    aa, ab = a.getchannel('A'), b.getchannel('A')
    from PIL import Image
    amask = ImageChops.lighter(aa, ab) if False else aa.point(lambda v: 255 if v > 8 else 0)
    bmask = ab.point(lambda v: 255 if v > 8 else 0)
    m = ImageChops.multiply(amask, bmask)
    m2 = m.point(lambda v: 255 if v > 0 else 0)
    return mask, m2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('archive')
    ap.add_argument('member')
    ap.add_argument('--layer', type=int, default=None, help='PNA 层号（0 基）')
    ap.add_argument('--box', help='x0,y0,x1,y1（省略则自动）')
    ap.add_argument('--zoom', type=int, default=4)
    ap.add_argument('--out')
    a = ap.parse_args()

    from PIL import Image, ImageChops, ImageDraw
    da, db = member(a.archive, a.member), member(a.archive, a.member)
    dr = member(a.archive, a.member)  # noqa  (ref 用 JP，alt 用 asset)

    def load(side, data):
        if a.member.upper().endswith('.PNA'):
            p = pna.load(data)
            i = a.layer if a.layer is not None else 0
            return p, Image.open(io.BytesIO(p['images'][i])).convert('RGBA')
        return None, Image.open(io.BytesIO(data)).convert('RGBA')

    # ref 从未被覆盖：JP 目录
    ref_data = None
    for nb, d in arcbuild.read_raw(JP / a.archive):
        if nb.decode('utf-16le').upper() == a.member.upper():
            ref_data = d
    alt_data = None
    for nb, d in arcbuild.read_raw(ASSET / a.archive):
        if nb.decode('utf-16le').upper() == a.member.upper():
            alt_data = d
    if ref_data is None or alt_data is None:
        raise SystemExit('缺一侧：ref=%s alt=%s' % (ref_data is not None, alt_data is not None))

    pref, iref = load('ref', ref_data)
    palt, ialt = load('alt', alt_data)
    if iref.size != ialt.size:
        raise SystemExit('两侧尺寸不同 %s ⇄ %s' % (iref.size, ialt.size))

    box = None
    if a.box:
        box = tuple(int(v) for v in a.box.split(','))
    else:
        mask, m2 = diff_box(iref, ialt)
        bb = m2.getbbox()
        if bb:
            pad = 24
            box = (max(0, bb[0] - pad), max(0, bb[1] - pad),
                   min(iref.width, bb[2] + pad), min(iref.height, bb[3] + pad))
        else:
            box = (0, 0, min(iref.width, 200), min(iref.height, 200))
    print('差异区 %s（图幅 %s）' % (box, iref.size))

    ca, cb = iref.crop(box), ialt.crop(box)
    z = a.zoom
    ca = ca.resize((ca.width * z, ca.height * z), Image.NEAREST)
    cb = cb.resize((cb.width * z, cb.height * z), Image.NEAREST)
    pad = 12
    W = ca.width + cb.width + pad * 3
    H = max(ca.height, cb.height) + pad * 2 + 22
    out = Image.new('RGBA', (W, H), (24, 24, 28, 255))
    out.paste(ca, (pad, pad + 22), ca)
    out.paste(cb, (pad * 2 + ca.width, pad + 22), cb)
    d = ImageDraw.Draw(out)
    d.text((pad, 6), 'REF (原版)', fill=(255, 220, 120, 255))
    d.text((pad * 2 + ca.width, 6), 'ALT (Steam)', fill=(120, 220, 255, 255))
    # 差异热区
    diff = ImageChops.difference(iref, ialt).convert('L').crop(box)
    diff = diff.point(lambda v: min(255, v * 6)).convert('RGB')
    diff = diff.resize((diff.width * z, diff.height * z), Image.NEAREST)
    out.paste(diff, (pad, pad * 2 + 22 + ca.height))
    d.text((pad, pad + 22 + ca.height), 'DIFF x6', fill=(255, 120, 120, 255))

    path = a.out or str(ROOT / 'tmp' / ('crop_%s.png' % Path(a.member).stem))
    out.convert('RGB').save(path)
    print('已写出 %s（%dx%d）' % (path, out.width, out.height))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
