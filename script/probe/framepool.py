"""图层池比对：按像素哈希配对两侧图层，判断“重打包”还是“内容被改”。

事件 CG 常把动画的每一帧各存为一个整幅不透明图层，因此合成画布只会剩下最后一帧，
逐层按 id 配对也会因 Steam 重排索引而失真。正确口径是把两侧图层看成**帧池**：
若原版每一帧都能在 Steam 侧找到像素一致的另一帧，则只是重打包（非和谐）；
否则差集里的帧就是被改绘的内容。

用法: python script/probe/framepool.py <archive> <member> [<member> ...] [--names-file=PATH]
"""
import hashlib
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tool import pna, arcstream

JP = ROOT.parent / '抬头看看吧看那天上的繁星'
STEAM = ROOT / 'backup'


def get(base, archive, name):
    path = base / archive
    if not path.exists():
        return None
    data_start, index = arcstream.read_index(path)
    for nb, rel, size in index:
        if nb.decode('utf-16le').upper() == name.upper():
            with open(path, 'rb') as fh:
                fh.seek(data_start + rel)
                return fh.read(size)
    return None


class Doc:
    def __init__(self, raw):
        from PIL import Image
        self.pna = pna.load(raw)
        self.imgs = {}
        self.layers = []
        for i, (e, img) in enumerate(zip(self.pna['entries'], self.pna['images'])):
            if not img:
                continue
            im = Image.open(io.BytesIO(img)).convert('RGBA')
            self.imgs[i] = im
            self.layers.append({
                'i': i, 'lid': e[1], 'box': (e[2], e[3], e[4], e[5]), 'size': im.size,
                'sha': hashlib.sha1(im.tobytes()).hexdigest(),
                'coarse': im.convert('RGB').resize((40, 24)).tobytes(),
            })


def l1(a, b):
    return sum(abs(x - y) for x, y in zip(a, b))


def main():
    from PIL import ImageChops
    sys.stdout.reconfigure(encoding='utf-8')
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    archive = args[0]
    names = args[1:]
    nf = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--names-file=')), None)
    if nf:
        names += [ln.strip() for ln in Path(nf).read_text(encoding='utf-8').splitlines()
                  if ln.strip() and not ln.startswith('#')]
    for name in names:
        dr, ds = get(JP, archive, name), get(STEAM, archive, name)
        if dr is None or ds is None:
            print('%-16s 缺一侧 jp=%s steam=%s' % (name, dr is not None, ds is not None))
            continue
        djp, dst = Doc(dr), Doc(ds)
        pool = {l['sha']: l for l in dst.layers}
        unmatched = [l for l in djp.layers if l['sha'] not in pool]
        matched = len(djp.layers) - len(unmatched)
        extra = [l for l in dst.layers if l['sha'] not in {x['sha'] for x in djp.layers}]
        print('\n%s  画布 %dx%d  原版层 %d / Steam 层 %d' % (
            name, djp.pna['canvas_w'], djp.pna['canvas_h'], len(djp.layers), len(dst.layers)))
        print('   帧池命中 %d / 未配对 %d / Steam 侧多出的帧 %d' % (matched, len(unmatched), len(extra)))
        for l in unmatched:
            cands = [x for x in dst.layers if x['size'] == l['size']]
            best = None
            for c in cands:
                d = l1(l['coarse'], c['coarse'])
                if best is None or d < best[0]:
                    best = (d, c)
            if best is None:
                print('   JP lid=%-3d size=%dx%d → Steam 无同尺寸帧' % (
                    l['lid'], l['size'][0], l['size'][1]))
                continue
            a, b = djp.imgs[l['i']], dst.imgs[best[1]['i']]
            diff = ImageChops.difference(a.convert('RGB'), b.convert('RGB')).convert('L')
            hist = diff.histogram()
            n = a.width * a.height
            ratio = sum(hist[9:]) / n * 100
            peak = max(i for i, v in enumerate(hist) if v > 0) if any(hist) else 0
            bbox = diff.point(lambda v: 255 if v > 8 else 0).getbbox()
            print('   JP lid=%-3d size=%dx%d → 最近 Steam lid=%-3d 差>8 %8.4f%% 峰值 %3d bbox %s' % (
                l['lid'], l['size'][0], l['size'][1], best[1]['lid'], ratio, peak, bbox))


if __name__ == '__main__':
    main()
