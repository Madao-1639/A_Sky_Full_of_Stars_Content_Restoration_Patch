"""PNA **合成画布**比较：把两侧各层按 box 贴回画布，再比像素。

用于「逐层配对不可靠（层数/内嵌尺寸不同）」的情形（如 `*X` 变体：原版少数大层 ⇄ Steam
重打包的许多小层）——此时逐层比毫无意义，但**合成结果可能完全一致**。

用法:
  python script/probe/compose_diff.py <archive> <member.pna> [--out PATH]
  python script/probe/compose_diff.py --batch <names-file>
"""
import argparse
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tool import arcbuild, pna, arcstream

JP = ROOT.parent / '抬头看看吧看那天上的繁星'
ASSET = ROOT / 'asset'


def get(base, archive, name):
    """只读目标成员（用 arcstream 的索引 + seek），不把整个归档读进内存。"""
    path = base / archive
    data_start, index = arcstream.read_index(path)
    for nb, rel, size in index:
        if nb.decode('utf-16le').upper() == name.upper():
            with open(path, 'rb') as fh:
                fh.seek(data_start + rel)
                return fh.read(size)
    return None


def locate(name):
    for arc in sorted((ASSET).glob('*.arc')):
        for nm in arcstream.names(arc):
            if nm.upper() == name.upper():
                return arc.name
    return None


def compose(p):
    from PIL import Image
    cv = Image.new('RGBA', (p['canvas_w'], p['canvas_h']), (0, 0, 0, 0))
    for e, img in zip(p['entries'], p['images']):
        if not img:
            continue
        x, y = e[2], e[3]
        try:
            im = Image.open(io.BytesIO(img)).convert('RGBA')
        except Exception:
            continue
        cv.alpha_composite(im, (int(x), int(y)))
    return cv


def compare(name, save=None):
    from PIL import Image, ImageChops
    arc = locate(name)
    if not arc:
        return '%s: 未定位归档' % name
    dr, da = get(JP, arc, name), get(ASSET, arc, name)
    if dr is None or da is None:
        return '%s: 缺一侧（JP=%s, asset=%s）' % (name, dr is not None, da is not None)
    pr, pa = pna.load(dr), pna.load(da)
    if (pr['canvas_w'], pr['canvas_h']) != (pa['canvas_w'], pa['canvas_h']):
        return '%s: 画布不同 %sx%s ⇄ %sx%s' % (name, pr['canvas_w'], pr['canvas_h'],
                                              pa['canvas_w'], pa['canvas_h'])
    cr, ca = compose(pr), compose(pa)
    # α 并集掩膜
    ar = cr.getchannel('A').point(lambda v: 255 if v > 8 else 0)
    aa = ca.getchannel('A').point(lambda v: 255 if v > 8 else 0)
    m = ImageChops.multiply(ar, aa)
    d = ImageChops.difference(cr.convert('RGB'), ca.convert('RGB'))
    d = ImageChops.multiply(d, m.convert('RGB'))
    hist = d.convert('L').histogram()
    n_vis = sum(m.histogram()[1:])
    n_diff = sum(hist[9:])          # 通道差 >8
    peak = max(i for i, v in enumerate(hist) if v > 0) if any(hist) else 0
    bbox = d.convert('L').point(lambda v: 255 if v > 8 else 0).getbbox()
    ratio = (n_diff / n_vis * 100) if n_vis else 0.0
    verdict = '误报(合成一致)' if ratio < 0.01 and peak <= 16 else '真差异'
    line = '%-18s 层 %d/%d  合成后可见像素 %d  差>8 %.4f%%  峰值 %d  bbox %s  → %s' % (
        name, pr['layer_count'], pa['layer_count'], n_vis, ratio, peak, bbox, verdict)
    if save:
        from PIL import ImageDraw
        a = cr.resize((520, int(520 * cr.height / cr.width)))
        b = ca.resize((520, int(520 * ca.height / ca.width)))
        h = a.height + 30
        out = Image.new('RGB', (1064, h), (24, 24, 28))
        out.paste(a, (8, 24), a)
        out.paste(b, (536, 24), b)
        dr_ = ImageDraw.Draw(out)
        dr_.text((8, 6), 'JP 合成 层%d' % pr['layer_count'], fill=(255, 220, 120))
        dr_.text((536, 6), 'Steam 合成 层%d' % pa['layer_count'], fill=(120, 220, 255))
        out.save(save)
        # 差异区高倍放大
        if bbox:
            pad = 20
            bx = (max(0, bbox[0] - pad), max(0, bbox[1] - pad),
                  min(cr.width, bbox[2] + pad), min(cr.height, bbox[3] + pad))
            z = max(1, min(6, 900 // max(1, bx[2] - bx[0])))
            ca_ = cr.crop(bx).resize(((bx[2] - bx[0]) * z, (bx[3] - bx[1]) * z), Image.LANCZOS)
            cb_ = ca.crop(bx).resize(((bx[2] - bx[0]) * z, (bx[3] - bx[1]) * z), Image.LANCZOS)
            ch = cr.crop(bx).convert('RGB')
            diffi = ImageChops.difference(ch, ca.crop(bx).convert('RGB'))
            diffi = diffi.point(lambda v: min(255, v * 5))
            dd = diffi.resize(((bx[2] - bx[0]) * z, (bx[3] - bx[1]) * z), Image.LANCZOS)
            W = ca_.width + 32
            H = ca_.height * 2 + 44
            o2 = Image.new('RGB', (W, H), (24, 24, 28))
            o2.paste(ca_, (8, 22), ca_)
            o2.paste(cb_, (8, 22 + ca_.height + 22), cb_)
            d2 = ImageDraw.Draw(o2)
            d2.text((8, 4), 'JP bbox %s ×%d' % (str(bx), z), fill=(255, 220, 120))
            d2.text((8, 22 + ca_.height + 4), 'Steam', fill=(120, 220, 255))
            o2.save(str(save).replace('.png', '_zoom.png'))
    return line


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('archive', nargs='?')
    ap.add_argument('member', nargs='?')
    ap.add_argument('--batch')
    ap.add_argument('--out')
    a = ap.parse_args()
    if a.batch:
        outd = ROOT / 'tmp' / 'pending_synth'
        outd.mkdir(exist_ok=True)
        for ln in Path(a.batch).read_text(encoding='utf-8').splitlines():
            n = ln.strip()
            if not n or n.startswith('#'):
                continue
            save = outd / (Path(n).stem + '.png')
            print(compare(n, save=str(save)))
        print('\n合成对照图 → %s' % outd)
    else:
        print(compare(a.member, a.out))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
