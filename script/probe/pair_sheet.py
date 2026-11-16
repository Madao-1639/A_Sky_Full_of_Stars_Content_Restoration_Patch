"""图层对照图：把两侧 PNA 的指定图层上下拼接，供人工目视裁定。

选择器三种：图层表**下标**（整数）、`lid:<n>`（按 entry 的 layer_id 定位，Steam 重排图层
表后只能用这个）、`png`（成员本身就是 PNG）。`--bbox` 把画面裁到差异外接框并放大到给定
宽度 —— 定点擦除在全图尺寸下看不出来，必须裁出差区放大。`--heat` 再拼一行差异热力图
（逐像素最大通道差 × `--gain` 后伪彩），标出峰值与 >8 占比。

用法: python script/probe/pair_sheet.py <archive> <member> <jp_sel> <steam_sel>
        [--w=1240] [--bbox] [--heat] [--gain=8]
"""
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageChops, ImageDraw, ImageOps  # noqa: E402

from tool import arcstream, pna  # noqa: E402

JP = ROOT.parent / '抬头看看吧看那天上的繁星'   # 原始安装，只读
STEAM = ROOT / 'backup'                        # Steam 原版基线，只读
OUT = ROOT / 'tmp' / 'pair'


def member(base, arc, name):
    data_start, entries = arcstream.read_index(base / arc)
    for nb, rel, size in entries:
        if nb.decode('utf-16-le').upper() == name.upper():
            with open(base / arc, 'rb') as fh:
                fh.seek(data_start + rel)
                return fh.read(size)
    raise SystemExit('missing %s/%s in %s' % (arc, name, base))


def layer(data, sel):
    """按选择器取出一张 RGBA 图。"""
    if sel == 'png':
        return Image.open(io.BytesIO(data)).convert('RGBA')
    doc = pna.load(data)
    if str(sel).startswith('lid'):
        for i, e in enumerate(doc['entries']):
            if e[1] == int(sel[3:].lstrip(':')):
                sel = i
                break
        else:
            raise SystemExit('no layer_id %s' % sel)
    raw = doc['images'][int(sel)]
    if raw is None:
        raise SystemExit('layer %s is a sentinel with no image' % sel)
    return Image.open(io.BytesIO(raw)).convert('RGBA')


def _diff_mask(a, b):
    """两图逐像素「最大通道绝对差」（L 模式）。"""
    n = min(a.width, b.width), min(a.height, b.height)
    d = ImageChops.difference(a.convert('RGB').resize(n), b.convert('RGB').resize(n))
    mx = d.split()[0]
    for c in d.split()[1:]:
        mx = ImageChops.lighter(mx, c)
    return mx


def diff_bbox(a, b, over=8):
    """两图 RGB 通道差超过 over 的外接框；无差异返回 None。"""
    return _diff_mask(a, b).point(lambda v: 255 if v > over else 0).getbbox()


def _resize_w(im, w):
    if w and im.width != w:
        im = im.resize((w, max(1, int(round(im.height * w / im.width)))), Image.LANCZOS)
    return im


def heat(a, b, gain, box=None, w=None):
    """差异热力图：通道差 ×gain 截断后伪彩，附带峰值与 >8 占比读数。"""
    mx = _diff_mask(a, b)
    if box:
        mx = mx.crop(box)
    peak = mx.getextrema()[1]
    over = sum(mx.histogram()[9:])
    ratio = 100.0 * over / (mx.width * mx.height)
    ramp = ImageOps.colorize(mx.point(lambda v: min(255, v * gain)),
                             black=(10, 10, 34), mid=(208, 40, 40), white=(255, 236, 96))
    return _resize_w(ramp.convert('RGB'), w), 'x%d  peak %d  >8 %.4f%%' % (gain, peak, ratio)


def flatten(im, box=None, w=None):
    if box:
        im = im.crop(box)
    im = _resize_w(im, w)
    bg = Image.new('RGBA', im.size, (96, 96, 96, 255))
    bg.alpha_composite(im)
    return bg.convert('RGB')


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    argv = [a for a in sys.argv[1:] if not a.startswith('--')]
    flags = [a for a in sys.argv[1:] if a.startswith('--')]
    opt = lambda p, d: next((a.split('=')[1] for a in flags if a.startswith(p)), d)  # noqa: E731
    w = int(opt('--w=', 1240))
    gain = int(opt('--gain=', 8))
    arc, name, ji, si = argv[0], argv[1], argv[2], argv[3]
    a = layer(member(JP, arc, name), ji)
    b = layer(member(STEAM, arc, name), si)
    box = None
    if '--bbox' in flags:
        bb = diff_bbox(a, b)
        if not bb:
            raise SystemExit('no visible difference in RGB')
        pad_x, pad_y = (bb[2] - bb[0]) // 4, (bb[3] - bb[1]) // 4
        box = (max(0, bb[0] - pad_x), max(0, bb[1] - pad_y),
               min(a.width, b.width, bb[2] + pad_x), min(a.height, b.height, bb[3] + pad_y))
        w = max(w, min(bb[2] - bb[0], 1240) * 4)
    rows = [('JP    %s/%s  #%s  %s' % (arc, name, ji, w), (255, 255, 0), flatten(a, box, w)),
            ('STEAM %s/%s  #%s' % (arc, name, si), (0, 220, 255), flatten(b, box, w))]
    if '--heat' in flags:
        hm, stats = heat(a, b, gain, box, w)
        rows.append(('DIFF  %s  %s' % (stats, box or '全幅'), (255, 96, 255), hm))
    sheet = Image.new('RGB', (max(im.width for _, _, im in rows),
                              sum(im.height for _, _, im in rows) + 22 * len(rows)),
                      (12, 12, 12))
    dr = ImageDraw.Draw(sheet)
    y = 0
    for label, color, im in rows:
        dr.text((6, y + 2), label, fill=color)
        sheet.paste(im, (0, y + 22))
        y += im.height + 22
    OUT.mkdir(parents=True, exist_ok=True)
    safe = lambda s: re.sub(r'\W', '', str(s))  # noqa: E731  (Windows 文件名不接受 : 等)
    suffix = ('_bbox' if box else '') + ('_heat' if '--heat' in flags else '')
    path = OUT / ('%s__%s__%s-%s%s.png'
                  % (arc[:-4], Path(name).stem, safe(ji), safe(si), suffix))
    sheet.save(path)
    print('%s  %dx%d' % (path, sheet.width, sheet.height))


if __name__ == '__main__':
    main()
