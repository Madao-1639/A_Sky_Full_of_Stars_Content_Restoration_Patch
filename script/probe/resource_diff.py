"""资源内容级比对：日文原版 vs Steam 基线，逐项给出三分类结论与证据。

为什么按内容而不是按文件名判：两套版本里同名资源内容可能不同（PNA 的 layer_id 是
纯位置量，Steam 版删改过图层），也可能**不同名却同内容**（见 `--cross-scan`）。
所以判据是两级——先按名定位，再按内容定论：

    同名 + 内容相同   -> SAME          引用 Steam 名，补丁里不必重复部署这一份
    同名 + 内容不同   -> CONFLICT      同名冲突，必须命名空间隔离（改名引入）
    Steam 侧查无此名  -> STEAM_MISSING 引入原版资源、沿用原版名
    原版侧查无此名    -> JP_MISSING    （信息项）Steam 独有，与还原无关

CONFLICT 还要再问一句"**这一份是不是已经处理过了**"——隔离副本（`ORG_` / 9X 段位）
可能早就部署在 `asset/` 里了，那就零新增，直接引用隔离名即可。于是 CONFLICT 带一个
子判定 `isolation`（不改变 `verdict` 本身的语义，向后兼容）：

    隔离副本存在 + 内容 == 原版 -> HANDLED            已处理，输出该引用的隔离名，零新增
    隔离副本不存在              -> NEEDS_ISOLATION    未处理，输出建议的隔离名与目标归档
    隔离副本存在 + 内容 != 原版 -> ISOLATION_MISMATCH 错配（错误级！见 lessons-learned 第五类缺陷）

"内容 == 原版"按上面同一套格式判据验（PNG 逐像素 / PNA 逐层 / OGG 时长 / WAV 时长 / 其余字节），
**不是**只看字节——隔离副本可能是重压缩过的同一幅画。

隔离名解析（沿用项目既有约定，不自己发明）：
    角色立绘  `ORG_<原名>`（`Aひかり_02L.pna` -> `ORG_Aひかり_02L.pna`，st* 槽接受该前缀）
    事件 CG   查 `resource/cg-conflicts.json` 的 `original -> patch` 映射（不按命名规则猜）
    其它类型  无既有约定 -> 一律归 NEEDS_ISOLATION

`--isolation-verdicts` 可把子判定提升为主 `verdict`（扁平三分类，便于 `jq` 之类按 verdict 过滤）；
不给该开关时 `verdict` 仍是 `CONFLICT`，只是报告里多一列/一节。`--no-isolation-check`
关掉整个判定，输出与增补前一致。

`--rejudge` 再对每条 CONFLICT 做一遍**像素级复核**（同名冲突的初判只看"逐像素 sha 相同吗"，
差一个像素就命中；两版分辨率/重采样/整体调色有出入、或差异只落在透明区/从不被显示的图层上，
都会误命中）。复核在 α 并集掩膜下算归一化像素差（不同像素占比 / 差异 bbox / 峰值），并查
"差异层是否会被引用脚本的 `0x39` 选中显示"，给出三档：**真冲突**（差异会被看到 → 保留原版的
隔离副本）/ **误报**（差异不可见或属噪声级 → 直接用 Steam 裸名，少部署一份）/ **待定**（尺寸或
结构不一致、语料缺失 → 上报人工核，不猜）。`--rejudge` 时 md 输出切换为重判报告。

"内容相同"按格式分别定义（这是本工具存在的理由——格式不同，可复用的判据不同）：

    PNG   逐像素比对（归一化到 RGBA 后比像素；调色板顺序、压缩级别不同但画面相同 -> 相同）
    PNA   比结构（canvas、layer_count、unknown、逐层 u0/layer_id/box/size）+ 逐层内嵌 PNG
          的逐像素比对；差异层给出层号与（可比的）像素级量化
    OGG   比时长（采样数 / 采样率）；时长不同即判不同。字节是否相同另列为证据
    WAV   比时长（编码、音量差异不判不同）
    其它  按字节比对（脚本 .WS2 / 文本 .LNG 只报字节异同，不做语义比对）

PNA 内部的 PNG 用 tool/pna.py 拆；归档成员用 tool/arcstream.py 的 read_index 按名
定位后 seek 读取（Chip1A.arc 约 1GB，不整份读进内存）。

输入（三种模式，可混用）：
    一组资源名          位置参数，或 --names-file（每行一个，可写 `归档名:成员名`）
    一个归档名          --arc Chip1.arc（枚举该归档两边的全部成员逐个比对）
    一段脚本的引用      --seam <steam_stem> <orig_stem>   或   --script <stem> --script-side jp

用法：
    python script/probe/resource_diff.py BG_20G_X1.PNG Aひかり_02L.PNA HIKA_2127.OGG
    python script/probe/resource_diff.py --names-file tmp/pilot_names.txt --cross-scan --suggest-rename
    python script/probe/resource_diff.py --seam yozora_hika_103e_E yozora_hika_103e -o tmp/x.md
    python script/probe/resource_diff.py --arc Chip1.arc --format csv --limit 50
    python script/probe/resource_diff.py --seam <steam_stem> <orig_stem> --isolation-summary-only
    python script/probe/resource_diff.py --seam <steam_stem> <orig_stem> --isolation-verdicts
    python script/probe/resource_diff.py --names-file tmp/rejudge_names.txt --rejudge -o tmp/conflict_rejudge.md

退出码：0 = 全部解析成功；2 = 至少一项解析失败（逐项打印原因，不静默跳过）；
        3 = 无解析失败但有 ISOLATION_MISMATCH（隔离错配是错误级，必须人工介入）。
"""
import argparse
import csv
import hashlib
import io
import json
import re
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from tool import arcstream, pna, ws2                                     # noqa: E402
from ws2_events import PNA as PNA_RE, RES as RES_RE, TEXT as TEXT_RE     # noqa: E402

SIDES = {
    'jp': ROOT.parent / '抬头看看吧看那天上的繁星',   # 2015 原始安装（只读）
    'steam': ROOT / 'backup',                        # Steam 原版基线
    'asset': ROOT / 'asset',                         # 打补丁后（仅作改名占位检查）
}
REF, ALT = 'jp', 'steam'    # 原版侧 / 要复用其资源的那一侧

VERDICT_LABEL = {
    'SAME': '相同',
    'CONFLICT': '同名冲突',
    'STEAM_MISSING': 'Steam 缺失',
    'JP_MISSING': '原版缺失',
    'ABSENT_BOTH': '两侧均无',
    'ERROR': '解析失败',
    # --isolation-verdicts 时会被提升为主 verdict（默认只作子判定，见 ISOLATION_LABEL）
    'HANDLED': '已处理',
    'NEEDS_ISOLATION': '未处理',
    'ISOLATION_MISMATCH': '隔离错配',
}
ISOLATION_LABEL = {
    'HANDLED': '已处理',
    'NEEDS_ISOLATION': '未处理',
    'ISOLATION_MISMATCH': '隔离错配',
}
BY_EXT = {'.PNG': 'png', '.PNA': 'pna', '.OGG': 'ogg', '.WAV': 'wav'}
CG_RE = re.compile(r'^[A-Z]{3}_\d\d[LS]$')
PORTRAIT_RE = re.compile(r'^[A-P][^_]*_\d\d[LMSWX]$')
SIZE_VARIANT_RE = re.compile(r'[LMSWX]$')          # 尺寸/差分后缀 L/M/S/W/X
MAX_PIXELS = 80 * 1000 * 1000     # 单幅像素上限，超过则报清晰错误（可用 --max-pixels 调高）
CG_CONFLICTS = ROOT / 'resource' / 'cg-conflicts.json'
_CG_MAP = None


class ResourceError(Exception):
    """单项无法解析/取用——由调用方记为该项目的 ERROR 结论。"""


def is_cg_stem(base):
    """事件 CG 的 stem（`HIK_09L` 式，3 个路线字母 + 两位编号 + L/S）。"""
    return bool(CG_RE.match(base))


def is_portrait_stem(base):
    """角色立绘的 stem（`Aひかり_02L` 式）。必须排除事件 CG——`COM_01L` 也满足
    `[A-P][^_]*_\\d\\d[LMSWX]`，路线代码恰好都落在 A–P 之间。"""
    return bool(PORTRAIT_RE.match(base)) and not is_cg_stem(base)


def cg_conflicts_map():
    """`resource/cg-conflicts.json` -> {(原版 stem 大写): (patch, archive, variants)}。

    事件 CG 的隔离名**只能**来自这张表（项目既有约定），不按命名规则猜 9X 段位。
    表不存在时返回空 dict（退化为"无既有约定"= NEEDS_ISOLATION），不抛异常。
    """
    global _CG_MAP
    if _CG_MAP is None:
        _CG_MAP = {}
        try:
            raw = json.loads(CG_CONFLICTS.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return _CG_MAP
        for c in raw.get('conflicts', []):
            _CG_MAP[c['original'].upper()] = (c['patch'], c.get('archive'),
                                              c.get('variants', {}))
    return _CG_MAP


def sha(data):
    return hashlib.sha256(data).hexdigest()


def human(n):
    x = float(n)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if x < 1024 or unit == 'GB':
            return '%d%s' % (x, unit) if unit == 'B' else '%.1f%s' % (x, unit)
        x /= 1024.0


# --------------------------------------------------------------------------
# 归档访问：只读成员表 + 按名 seek 取载荷
# --------------------------------------------------------------------------
class Side:
    def __init__(self, name, root):
        self.name = name
        self.root = root
        self.archives = sorted(p for p in root.glob('*.arc'))
        self._index = None
        self._data_start = {}
        self._fp = {}

    def index(self):
        """{UPPER_NAME: (archive, rel, size, orig_name)}，只读成员表，不读载荷。"""
        if self._index is None:
            idx = {}
            for arc in self.archives:
                data_start, entries = arcstream.read_index(arc)
                self._data_start[arc.name.upper()] = data_start
                for nb, rel, size in entries:
                    orig = nb.decode('utf-16le')
                    idx.setdefault(orig.upper(), (arc.name, rel, size, orig))
            self._index = idx
        return self._index

    def locate(self, name):
        return self.index().get(name.upper())

    def fetch(self, name, hint=None):
        """按名取成员字节。hint 为归档名时要求命中该归档，否则报错。"""
        hit = self.locate(name)
        if hit is None:
            raise ResourceError('%s: 在 %s 下任何归档中都不存在' % (name, self.root))
        arc_name, rel, size, orig = hit
        if hint and arc_name.upper() != hint.upper():
            raise ResourceError('%s: 实际位于 %s，与限定的 %s 不符' % (name, arc_name, hint))
        path = self.root / arc_name
        data_start = self._data_start.get(arc_name.upper())
        if data_start is None:
            data_start, _ = arcstream.read_index(path)
            self._data_start[arc_name.upper()] = data_start
        with open(path, 'rb') as fh:
            fh.seek(data_start + rel)
            data = fh.read(size)
        if len(data) != size:
            raise ResourceError('%s: %s 中该成员被截断（读到 %d / 成员表声明 %d）'
                                % (name, arc_name, len(data), size))
        return data, arc_name, orig

    def load(self, name, hint=None):
        """(info, raw)。info 按名缓存（只存哈希与结构，不存原始字节）。"""
        data, arc_name, orig = self.fetch(name, hint)
        info = self._fp.get(orig.upper())
        if info is None:
            info = info_of(orig, data, arc_name)
            self._fp[orig.upper()] = info
        return info, data


# --------------------------------------------------------------------------
# 各格式的解析
# --------------------------------------------------------------------------
def info_of(name, data, arc_name):
    kind = BY_EXT.get(Path(name).suffix.upper())
    if kind is None:
        return {'kind': 'raw', 'name': name, 'arc': arc_name, 'nbytes': len(data),
                'byte_sha': sha(data)}
    return globals()['info_' + kind](name, data, arc_name)


def _open_rgba(data, name, what):
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as exc:
        raise ResourceError('%s: 内嵌/独立 PNG 不可读（%s）' % (name, exc))
    if im.width * im.height > MAX_PIXELS:
        raise ResourceError('%s: %s 为 %dx%d，超过 --max-pixels 上限（%d）'
                            % (name, what, im.width, im.height, MAX_PIXELS))
    return im, im.convert('RGBA')


def info_png(name, data, arc_name, what='PNG'):
    im, rgba = _open_rgba(data, name, what)
    px = rgba.tobytes()
    return {'kind': 'png', 'name': name, 'arc': arc_name, 'nbytes': len(data),
            'byte_sha': sha(data), 'w': im.width, 'h': im.height, 'mode': im.mode,
            'pixel_sha': sha(px)}


def info_pna(name, data, arc_name):
    try:
        p = pna.load(data)
    except Exception as exc:
        raise ResourceError('%s: 不是可读的 PNAP（%s）' % (name, exc))
    layers = []
    for i, e in enumerate(p['entries']):
        img = p['images'][i]
        entry = {'u0': e[0], 'lid': e[1], 'box': tuple(e[2:6]), 'reserved': e[6],
                 'marker': (e[7], e[8]), 'size': e[9], 'pixel_sha': None, 'byte_sha': None}
        if img:
            entry['byte_sha'] = sha(img)
            try:
                entry['pixel_sha'] = info_png('%s#layer%d' % (name, i), img, arc_name,
                                              what='第 %d 层' % i)['pixel_sha']
            except ResourceError as exc:
                entry['pixel_sha'] = 'UNREADABLE'
                entry['unreadable'] = str(exc)
        layers.append(entry)
    return {'kind': 'pna', 'name': name, 'arc': arc_name, 'nbytes': len(data),
            'byte_sha': sha(data), 'canvas': (p['canvas_w'], p['canvas_h']),
            'layer_count': p['layer_count'], 'unknown': p['unknown'], 'layers': layers}


def _ogg_pages(data, name):
    """逐页解析 Ogg（不解码音频）：(codec, rate, channels, samples, pages, consumed)。"""
    if data[:4] != b'OggS':
        raise ResourceError('%s: 不是 Ogg 流（magic=%r）' % (name, data[:4]))
    codec = rate = channels = None
    granules = {}
    pages, off, first = 0, 0, True
    while off + 27 <= len(data) and data[off:off + 4] == b'OggS':
        ver, _htype, granule, serial, _seq, _crc, nsegs = struct.unpack_from(
            '<BBQIIIB', data, off + 4)
        if ver != 0:
            break
        body = off + 27 + nsegs
        plen = sum(data[off + 27:body])
        if body + plen > len(data):
            break
        if first and nsegs:
            pkt = data[body:body + plen]
            if pkt[:7] == b'\x01vorbis' and len(pkt) >= 16:
                codec, channels = 'vorbis', pkt[11]
                rate = struct.unpack_from('<I', pkt, 12)[0]
            elif pkt[:8] == b'OpusHead':
                codec, channels, rate = 'opus', pkt[9], 48000
            else:
                codec = 'unknown(%r)' % bytes(pkt[:8])
        first = False
        if granule != 0xFFFFFFFFFFFFFFFF:
            granules[serial] = max(granules.get(serial, 0), granule)
        pages += 1
        off = body + plen
    return codec, rate, channels, (max(granules.values()) if granules else 0), pages, off


def info_ogg(name, data, arc_name):
    codec, rate, channels, samples, pages, consumed = _ogg_pages(data, name)
    return {'kind': 'ogg', 'name': name, 'arc': arc_name, 'nbytes': len(data),
            'byte_sha': sha(data), 'codec': codec, 'sample_rate': rate,
            'channels': channels, 'samples': samples, 'pages': pages,
            'duration': (samples / float(rate)) if rate else None,
            'tail_bytes': len(data) - consumed}


def info_wav(name, data, arc_name):
    info = {'kind': 'wav', 'name': name, 'arc': arc_name, 'nbytes': len(data),
            'byte_sha': sha(data), 'sample_rate': None, 'channels': None, 'bits': None,
            'samples': None, 'duration': None}
    if data[:4] != b'RIFF' or data[8:12] != b'WAVE':
        raise ResourceError('%s: 不是 RIFF/WAVE（magic=%r）' % (name, bytes(data[:12])))
    off, data_size, block = 12, None, None
    while off + 8 <= len(data):
        cid = data[off:off + 4]
        csz = struct.unpack_from('<I', data, off + 4)[0]
        body = off + 8
        if cid == b'fmt ' and csz >= 16:
            channels, rate, _bps, block = struct.unpack_from('<HIIH', data, body)
            bits = struct.unpack_from('<H', data, body + 14)[0]
            info.update(channels=channels, sample_rate=rate, bits=bits)
        elif cid == b'data':
            data_size = csz
        off = body + csz + (csz & 1)
    if info['sample_rate'] and data_size and block:
        info['samples'] = data_size // block
        info['duration'] = info['samples'] / float(info['sample_rate'])
    return info


# --------------------------------------------------------------------------
# 判据键 + 证据
# --------------------------------------------------------------------------
def reuse_key(info):
    """"可复用 Steam 那一份吗" 的判据键——相同即视为内容相同。"""
    kind = info['kind']
    if kind == 'png':
        return ('png', info['w'], info['h'], info['pixel_sha'])
    if kind == 'pna':
        return ('pna', info['unknown']) + info['canvas'] + (info['layer_count'],) \
            + tuple((l['u0'], l['lid'], l['box'], l['reserved'], l['marker'], l['size'],
                     l['pixel_sha']) for l in info['layers'])
    if kind == 'ogg':
        return ('ogg', info['sample_rate'], info['samples'])
    if kind == 'wav':
        return ('wav', info['sample_rate'], info['samples'], info['channels'])
    return ('raw', info['byte_sha'])


def evidence(a, b, da, db):
    """(是否内容相同, 证据行)。a/b 为两侧 info，da/db 为原始字节。"""
    if a['kind'] != b['kind']:
        return False, ['两侧格式不同：原版 %s ⇄ Steam %s' % (a['kind'], b['kind'])]
    return globals()['_ev_' + a['kind']](a, b, da, db)


def _ev_png(a, b, da, db):
    dims = '原版 %dx%d(%s) ⇄ Steam %dx%d(%s)' % (a['w'], a['h'], a['mode'],
                                                 b['w'], b['h'], b['mode'])
    if a['pixel_sha'] == b['pixel_sha']:
        extra = '' if a['byte_sha'] == b['byte_sha'] \
            else '（字节不同：压缩/调色板差异，画面一致）'
        return True, ['像素完全一致 %s%s' % (dims, extra)]
    out = ['像素不同：%s' % dims]
    if (a['w'], a['h']) != (b['w'], b['h']):
        out.append('尺寸不一致 → 无法给出逐像素差异规模，直接判不同')
    else:
        out += png_delta(da, db)
    return False, out


def png_delta(da, db):
    """像素级差异量化：不同像素数/占比、峰值通道差、差异区 bbox。"""
    from PIL import Image, ImageChops
    ia = Image.open(io.BytesIO(da)).convert('RGBA')
    ib = Image.open(io.BytesIO(db)).convert('RGBA')
    if ia.size != ib.size:
        return ['尺寸不一致：%s ⇄ %s' % (ia.size, ib.size)]
    d = ImageChops.difference(ia, ib)
    mx = d.split()[0]
    for c in d.split()[1:]:
        mx = ImageChops.lighter(mx, c)
    hist = mx.histogram()
    ndiff, total = sum(hist[1:]), sum(hist)
    peak = max(v for v, n in enumerate(hist) if n) if ndiff else 0
    bbox = mx.point(lambda v: 255 if v else 0).getbbox() if ndiff else None
    lines = ['不同像素 %d / %d（%.4f%%），峰值通道差 %d/255，差异区 bbox=%s（画布 %s）'
             % (ndiff, total, 100.0 * ndiff / total, peak, bbox, ia.size)]
    if total and ndiff / total < 0.05:
        lines.append('形制：局部改写（差异像素 <5%，非整幅重绘）')
    return lines


def _ev_pna(a, b, da, db):
    meta_a = [(l['u0'], l['lid'], l['box'], l['reserved'], l['marker'])
              for l in a['layers']]
    meta_b = [(l['u0'], l['lid'], l['box'], l['reserved'], l['marker'])
              for l in b['layers']]
    out = ['结构：canvas %s / %d 层 / unknown %d ⇄ canvas %s / %d 层 / unknown %d'
           % (a['canvas'], a['layer_count'], a['unknown'],
              b['canvas'], b['layer_count'], b['unknown'])]
    fields = []
    if a['canvas'] != b['canvas']:
        fields.append('canvas')
    if a['layer_count'] != b['layer_count']:
        fields.append('layer_count')
    if a['unknown'] != b['unknown']:
        fields.append('unknown')
    if len(a['layers']) != len(b['layers']):
        fields.append('layer 条数')
    meta_same = not fields and meta_a == meta_b
    if fields:
        out.append('结构字段不同：%s' % '、'.join(fields))
    n = min(len(a['layers']), len(b['layers']))
    meta_diff = [i for i in range(n) if meta_a[i] != meta_b[i]]
    px_diff = [i for i in range(n)
               if a['layers'][i]['pixel_sha'] != b['layers'][i]['pixel_sha']]
    reenc = [i for i in range(n) if a['layers'][i]['pixel_sha'] == b['layers'][i]['pixel_sha']
             and a['layers'][i]['byte_sha'] != b['layers'][i]['byte_sha']]
    size_diff = [i for i in range(n)
                 if a['layers'][i]['size'] != b['layers'][i]['size']]
    if meta_same:
        out.append('逐层元数据（u0/lid/box/reserved/marker）全部一致')
    if meta_diff:
        out.append('逐层元数据不同的层 %d / %d：%s'
                   % (len(meta_diff), n, _abbrev(meta_diff)))
    if size_diff:
        out.append('内嵌 PNG 字节数不同的层 %d / %d（重编码或换素材，'
                   '是否真的换画面看下面"像素不同"）：%s'
                   % (len(size_diff), n, _abbrev(size_diff)))
    if px_diff:
        out.append('**像素不同**的层 %d / %d：%s' % (len(px_diff), n, _abbrev(px_diff)))
        pa, pb = _pna_layers(da), _pna_layers(db)
        shown = 0
        for i in px_diff:
            if i < len(pa) and i < len(pb) and pa[i] and pb[i]:
                out.append('  第 %d 层：%s' % (i, '；'.join(png_delta(pa[i], pb[i]))))
                shown += 1
                if shown == 3:
                    break
        if len(px_diff) > shown:
            out.append('  （另有 %d 层像素不同，略）' % (len(px_diff) - shown))
    if reenc:
        out.append('像素相同、仅 PNG 编码不同（重压缩，画面一致）的层 %d / %d：%s'
                   % (len(reenc), n, _abbrev(reenc)))
    same = not fields and not meta_diff and not px_diff
    if same:
        out.append('结构与逐层画面全部一致')
        return True, out
    if meta_same and px_diff:
        out.append('→ 形制：结构完全一致、仅 %d 层被局部改写（非整份换素材）。'
                   '可考虑**图层级修复**（先例 resource/layer-repairs.json）而非改名隔离'
                   % len(px_diff))
    return False, out


def _pna_layers(data):
    try:
        return pna.load(data)['images']
    except Exception:
        return []


def _abbrev(nums, cap=12):
    nums = list(nums)
    head = ', '.join(str(i) for i in nums[:cap])
    return head if len(nums) <= cap else '%s … 其余 %d 个' % (head, len(nums) - cap)


def _ev_ogg(a, b, _da, _db):
    if not a['sample_rate'] or not b['sample_rate']:
        return False, ['无法解析采样率（原版 %r / Steam %r）→ 保守判不同'
                       % (a['codec'], b['codec'])]
    fa = '%.3fs（%d 采样 @%dHz，%s）' % (a['duration'], a['samples'], a['sample_rate'],
                                        a['codec'])
    fb = '%.3fs（%d 采样 @%dHz，%s）' % (b['duration'], b['samples'], b['sample_rate'],
                                        b['codec'])
    if (a['samples'], a['sample_rate']) != (b['samples'], b['sample_rate']):
        return False, ['时长不同：原版 %s ⇄ Steam %s（Δ%.3fs）'
                       % (fa, fb, a['duration'] - b['duration'])]
    out = ['时长一致：原版 %s ⇄ Steam %s' % (fa, fb)]
    if a['byte_sha'] != b['byte_sha']:
        out.append('字节不同（%s ⇄ %s）——同长度也可能是不同 take，建议人工听校'
                   % (human(a['nbytes']), human(b['nbytes'])))
    else:
        out.append('字节也一致')
    for tag, i in (('原版', a), ('Steam', b)):
        if i['tail_bytes']:
            out.append('%s：尾部 %d 字节不是完整 Ogg 页' % (tag, i['tail_bytes']))
    return True, out


def _ev_wav(a, b, _da, _db):
    if a['samples'] is None or b['samples'] is None:
        same = a['byte_sha'] == b['byte_sha']
        return same, ['无法解析时长 → 退回字节比对：%s' % ('一致' if same else '不同')]
    if (a['samples'], a['sample_rate']) != (b['samples'], b['sample_rate']):
        return False, ['时长不同：原版 %.3fs（%d 采样 @%dHz）⇄ Steam %.3fs（%d 采样 @%dHz）'
                       % (a['duration'], a['samples'], a['sample_rate'],
                          b['duration'], b['samples'], b['sample_rate'])]
    return True, ['时长一致：%.3fs（%d 采样 @%dHz）'
                  % (a['duration'], a['samples'], a['sample_rate'])]


def _ev_raw(a, b, _da, _db):
    same = a['byte_sha'] == b['byte_sha']
    return same, ['字节%s（原版 %s ⇄ Steam %s）——非图像/音频资源，只做字节级判断'
                  % ('一致' if same else '不同', human(a['nbytes']), human(b['nbytes']))]


# --------------------------------------------------------------------------
# 脚本资源名提取
# --------------------------------------------------------------------------
def names_in_script(side, stem):
    """一段 WS2 引用的资源名（PNA 槽引用 + PNG/OGG/WAV 直引），按出现位置保序去重。"""
    raw, _arc, _orig = side.fetch(stem.upper() + '.WS2')
    data = ws2.decode(raw)
    spans = [m.span() for m in TEXT_RE.finditer(data)]
    out, seen = [], set()

    def add(pos_name):
        pos, x = pos_name
        if x.upper() not in seen:
            seen.add(x.upper())
            out.append(x)

    found = []
    for m in PNA_RE.finditer(data):
        if not any(a <= m.start() < b for a, b in spans):
            found.append((m.start(), m.group(2).decode('shift_jis', 'replace') + '.PNA'))
    for m in RES_RE.finditer(data):
        if not any(a <= m.start() < b for a, b in spans):
            found.append((m.start(), m.group(1).decode('shift_jis', 'replace')))
    for item in sorted(found, key=lambda t: t[0]):
        add(item)
    return out


def name_sequence_diff(ref_names, alt_names):
    """两段脚本的**引用名序列**差异：抓"两侧都在引用资源、但引用的名字不同"。

    这正是只看三分类会漏掉的一类——`BG_20G_X1` 与 `BG_20D_X1` 两侧归档里都有、
    且各自逐字节相同，于是两项都判 SAME，可两侧脚本在同一个位置引用的**不是同一个**。
    """
    import difflib
    sm = difflib.SequenceMatcher(None, [n.upper() for n in ref_names],
                                 [n.upper() for n in alt_names], autojunk=False)
    rows = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            continue
        rows.append({'kind': {'replace': '换成', 'delete': '仅原版引用',
                              'insert': '仅 Steam 引用'}[tag],
                     'ref': ref_names[i1:i2], 'alt': alt_names[j1:j2]})
    return rows


# --------------------------------------------------------------------------
# 比对
# --------------------------------------------------------------------------
def compare(name, hint, ref, alt, asset=None):
    rec = {'name': name, 'hint': hint, 'arc': None, 'size': None, 'verdict': None,
           'evidence': [], 'alt_arc': None, 'alt_size': None, 'suggest': None,
           'suggest_reason': None, 'dup': None, '_keys': None,
           # 增补：同名冲突的处置状态（asset 为 None 时不判定，字段留空）
           'isolation': None, 'isolation_name': None, 'isolation_arc': None,
           'isolation_target': None, 'isolation_rule': None,
           # 增补：同名冲突的像素级复核（--rejudge 时填，见「重判」一节）
           'rejudge': None, 'rejudge_lines': None}
    try:
        ra, rb = ref.locate(name), alt.locate(name)
        if ra is None and rb is None:
            rec['verdict'] = 'ABSENT_BOTH'
            rec['evidence'] = ['两侧所有归档中都没有该名 → 该资源不在本补丁可比的归档集合内'
                               '（脚本却引用了它，说明它按别的途径分发，两侧一致，无需处理）']
            return rec
        if rb is None:
            info, _raw = ref.load(name, hint)
            rec.update(name=info['name'], arc=info['arc'], size=info['nbytes'],
                       verdict='STEAM_MISSING')
            rec['evidence'] = ['Steam 侧任何归档中查无此名 → 引入原版资源、沿用原版名',
                               '原版：%s（%s）' % (info['arc'], human(info['nbytes']))]
            rec['_keys'] = (reuse_key(info), None, info['byte_sha'], None)
            return rec
        if ra is None:
            info, _raw = alt.load(name, hint)
            rec.update(name=info['name'], alt_arc=info['arc'], alt_size=info['nbytes'],
                       verdict='JP_MISSING')
            rec['evidence'] = ['原版侧查无此名（Steam 独有，与还原无关）',
                               'Steam：%s（%s）' % (info['arc'], human(info['nbytes']))]
            rec['_keys'] = (None, reuse_key(info), None, info['byte_sha'])
            return rec
        fa, da = ref.load(name, hint)
        fb, db = alt.load(name, hint)
        rec.update(name=fa['name'], arc=fa['arc'], size=fa['nbytes'],
                   alt_arc=fb['arc'], alt_size=fb['nbytes'])
        same, ev = evidence(fa, fb, da, db)
        if fa['name'] != fb['name']:
            ev.append('两侧存档名大小写不同：原版 `%s` ⇄ Steam `%s`（本工具按不区分大小写匹配）'
                      % (fa['name'], fb['name']))
        rec['verdict'] = 'SAME' if same else 'CONFLICT'
        if same:
            ev.append('→ 引用 Steam 名 %s，补丁里不必再部署这一份' % fb['name'])
        else:
            ev.append('→ 同名冲突：必须命名空间隔离（改名引入）')
        rec['evidence'] = ev
        rec['_keys'] = (reuse_key(fa), reuse_key(fb), fa['byte_sha'], fb['byte_sha'])
        if not same and REJUDGE:
            rejudge_record(rec, da, db, fa)
        if not same and asset is not None:
            check_isolation(rec, ref, asset)
    except ResourceError as exc:
        rec['verdict'] = 'ERROR'
        rec['evidence'] = [str(exc)]
    return rec


# --------------------------------------------------------------------------
# 「同名冲突是否已经处理过」判定
# --------------------------------------------------------------------------
KIND_LABEL = {'png': 'PNG 逐像素', 'pna': 'PNA 逐层', 'ogg': 'OGG 时长',
              'wav': 'WAV 时长', 'raw': '字节'}


def isolation_candidate(name):
    """(建议/已用的隔离名 or None, 依据说明, 约定的目标归档 or None)。

    只认项目既有的两套约定，不做任何"按命名规则猜"：
      角色立绘 -> `ORG_<原名>`                     （st* 槽接受 ORG_ 前缀，已实测）
      事件 CG  -> `resource/cg-conflicts.json` 的 original→patch 映射（9X 段位）
      其它     -> 没有约定，返回 None（调用方归 NEEDS_ISOLATION）
    """
    base, ext = Path(name).stem, Path(name).suffix
    if is_cg_stem(base):
        # `HIK_09L` -> 路线 'HIK' / 编号 '09' / 变体 'L'（编号是 2 位，别用 base[3:5]）
        key, patch_of = '%s_%s' % (base[:3], base[4:6]), base[6:]
        hit = cg_conflicts_map().get(key)
        if hit is None:
            return None, ('事件 CG，但 resource/cg-conflicts.json 里查无 %s 的 '
                          'original→patch 映射（不按命名规则猜 9X 段位）' % key), None
        patch, arc, variants = hit
        note = ''
        v = variants.get(patch_of) or {}
        if v.get('steam') == 'missing':
            note = '；该变体 Steam 侧本就缺失'
        if v.get('deployed') is False:
            note += '；cg-conflicts.json 记该变体 deployed=false（当初按需只部署了另一变体）'
        return (patch + patch_of + ext,
                '事件 CG：resource/cg-conflicts.json 的 %s→%s 映射%s'
                % (key, patch, note), arc)
    if is_portrait_stem(base):
        return 'ORG_' + base + ext, '角色立绘：既有 `ORG_` 前缀约定（st* 槽接受）', None
    return None, ('既非角色立绘也非事件 CG，没有既有的隔离命名约定 → 归"未处理"'
                  '（`--suggest-rename` 给出的 ORG_ 候选仅供人工参考，槽位长度未实测）'), None


def _target_archive(asset_side, name, explicit):
    """隔离副本该放进哪个归档：优先映射表写明的，否则看裸名原件在 asset/ 的落点。"""
    if explicit:
        return explicit
    hit = asset_side.locate(name) if asset_side is not None else None
    return hit[0] if hit else None


def check_isolation(rec, ref, asset_side):
    """给一条 CONFLICT 记录补上 isolation 子判定 + 隔离名 + 证据（就地修改 rec）。"""
    name = rec['name']
    cand, rule, target = isolation_candidate(name)
    rec['isolation_rule'] = rule
    ev = list(rec['evidence'])

    if cand is None:
        rec['isolation'] = 'NEEDS_ISOLATION'
        ev.append('→ 隔离判定：**未处理**——%s' % rule)
        rec['evidence'] = ev
        return rec

    hit = asset_side.locate(cand)
    if hit is None:
        rec['isolation'] = 'NEEDS_ISOLATION'
        rec['isolation_name'] = cand
        rec['isolation_target'] = _target_archive(asset_side, name, target)
        ev.append('→ 隔离判定：**未处理**——隔离副本 `%s` 在 asset/ 中不存在（%s）'
                  % (cand, rule))
        ev.append('  需引入原版 `%s` 并命名为 `%s`，部署到 %s'
                  % (name, cand, rec['isolation_target'] or '（归档未定，需人工确认）'))
        rec['evidence'] = ev
        return rec

    iso_arc, iso_name = hit[0], hit[3]
    rec['isolation_name'] = iso_name
    rec['isolation_arc'] = iso_arc
    try:
        jp_info, jp_raw = ref.load(name)
        iso_info, iso_raw = asset_side.load(iso_name)
    except ResourceError as exc:
        rec['isolation'] = 'ISOLATION_MISMATCH'
        ev.append('→ 隔离判定：**隔离错配**（错误级）——隔离副本 `%s`（asset/%s）'
                  '取用或解析失败：%s' % (iso_name, iso_arc, exc))
        rec['evidence'] = ev
        return rec

    same, sub = evidence(jp_info, iso_info, jp_raw, iso_raw)
    kind = KIND_LABEL.get(jp_info['kind'], jp_info['kind'])
    if same:
        rec['isolation'] = 'HANDLED'
        ev.append('→ 隔离判定：**已处理**——`%s` 已存在于 asset/%s，且按「%s」判据'
                  '其内容 == 原版 %s' % (iso_name, iso_arc, kind, name))
        ev.append('  **直接引用隔离名 `%s`，零新增部署**' % iso_name)
        if iso_name != cand:
            ev.append('  （大小写与约定名 `%s` 不同，归档成员名按不区分大小写匹配）' % cand)
    else:
        rec['isolation'] = 'ISOLATION_MISMATCH'
        ev.append('⇉ 隔离判定：**隔离错配（错误级！doc/lessons-learned.md 第五类缺陷）**——'
                  '`%s` 存在于 asset/%s，但其内容 **!= 原版 `%s`**'
                  % (iso_name, iso_arc, name))
        ev += ['  ' + line for line in sub]
        ev.append('  该隔离副本里装的很可能是别的资源的数据——引擎不会报错，只会画面错乱。'
                  '必须人工核对后重新部署：`%s` ⇐ 原版 `%s`（按「%s」判据）'
                  % (iso_name, name, kind))
    rec['evidence'] = ev
    return rec


# --------------------------------------------------------------------------
# 重判：同名冲突的像素级复核
# --------------------------------------------------------------------------
# 为什么还要复核：初判只问"逐像素 sha 相同吗"——差一个像素就是 CONFLICT。两版
# 分辨率/重采样/整体调色稍有出入就会命中，可画面在**本作实际演出**里可能毫无差别
# （比如差异只落在从不被 0x39 选中的图层上，或全在透明区）。能留下 Steam 那份就
# 少部署一份资源，所以对每条 CONFLICT 再算一遍「归一化后的像素差异 + 差异会不会
# 被显示」，给出 真冲突 / 误报 / 待定 三档。判不了的一律"待定"上报，不猜。
#
# 判据（先做 α 并集掩膜，再比 RGB 通道差；阈值 8/255）：
#   可见像素差占比 = 0 且峰值 = 0                    -> 误报（画面等价，此前只因
#                                                     透明区 RGB 垃圾值/编码差异命中）
#   占比 < 0.5% 且峰值 <= 32                        -> 误报（重编码/亚像素噪声级）
#   PNA：差异层与全部引用脚本 0x39 选中的层无交集    -> 误报（差异层从不显示）
#   其余                                             -> 真冲突
# 一律待定（上报，不猜）：
#   - 两侧（或某层内嵌图）尺寸不同：要先缩放才可比，缩放本身引入误差
#   - PNA 层数或逐层元数据（u0/layer_id/box/reserved/marker）不一致：逐层配对不可靠
#   - asset/ 里没有脚本语料：可见性无从判断
#
# 掩膜是必须的：PNA 图层大面积 α=0，透明处 RGB 是垃圾值，不掩就等于自造假差异。
# 另附一项数值：把 Steam 那侧逐通道按 a·x+b 线性拟合到原版侧后的**残差**——
# 残差很小而原始差异很大，说明差异是整体调色/亮度变体（外观仍可辨，故不改结论）。
#
# 0x39 的帧值是**图层表下标**，不是 entry 里的 layer_id 字段：全语料 38642 个帧值
# 在下标解释下 100% 落在 u0=0 的真实图层，按 layer_id 解释有 19.5% 落到哨兵
# （见 tmp/frame_sem.py）。故可见性判定直接按下标求交集。
REJUDGE_LABEL = {'REAL': '真冲突', 'FALSE': '误报', 'UNDECIDED': '待定'}
NOISE_RATIO = 0.5        # 可见像素差占比低于此值……
NOISE_PEAK = 32          # ……且峰值不超过此值 -> 视作噪声级
GRADE_RESIDUAL = 0.5     # 线性校正后残差低于此值 -> 差异是整体调色/亮度
REJUDGE = False          # 由 --rejudge 打开
_DISPLAY_CACHE = {}
_BOUND_CACHE = set()      # 被 0x34 绑定过的资源名（含 ORG_ 去前缀形式），见 _is_bound()
_DISPLAY_SCANNED = False
_DISPLAY_OK = None


def _alpha_stats(ia, ib, over=8):
    """α 并集掩膜下的差异统计。ia/ib 必须是同尺寸 RGBA。

    visible     —— 至少一侧不透明的像素数（掩膜大小）
    alpha_ratio —— 其中 α 通道差 > over 的占比（%）
    rgb_ratio   —— 其中任一 RGB 通道差 > over 的占比（%）
    peak        —— 掩膜内最大通道差
    bbox        —— 差异区（含 α 差）外接框
    """
    from PIL import ImageChops
    sa, sb = ia.split(), ib.split()
    mask = ImageChops.lighter(sa[3], sb[3]).point(lambda v: 255 if v else 0)
    visible = sum(mask.histogram()[1:])
    if not visible:
        return {'visible': 0, 'alpha_ratio': 0.0, 'rgb_ratio': 0.0, 'peak': 0, 'bbox': None}
    da = ImageChops.multiply(ImageChops.difference(sa[3], sb[3]), mask)
    a_over = sum(da.histogram()[over + 1:])
    d = ImageChops.difference(ia.convert('RGB'), ib.convert('RGB'))
    mx = d.split()[0]
    for c in d.split()[1:]:
        mx = ImageChops.lighter(mx, c)
    mx = ImageChops.multiply(mx, mask)
    hist = mx.histogram()
    r_over = sum(hist[over + 1:])
    peak = max(v for v, n in enumerate(hist) if n) if sum(hist[1:]) else 0
    bbox = mx.point(lambda v: 255 if v else 0).getbbox() if r_over else None
    return {'visible': visible, 'alpha_ratio': 100.0 * a_over / visible,
            'rgb_ratio': 100.0 * r_over / visible, 'peak': peak, 'bbox': bbox}


def _set_side(ia, ib):
    """尺寸不同时把大的那侧等比缩到小的那侧（LANCZOS）；返回 (原版侧, steam 侧, 说明)。"""
    if ia.size == ib.size:
        return ia, ib, None
    if ia.width * ia.height <= ib.width * ib.height:
        small, big, which = ia, ib, 'Steam'
    else:
        small, big, which = ib, ia, '原版'
    note = ('两侧尺寸不同（原版 %s ⇄ Steam %s），已把%s那侧等比缩到 %s 再比'
            % (ia.size, ib.size, which, small.size))
    return small, big.resize(small.size, Image.LANCZOS), note


def _linear_residual(ia, ib):
    """把 Steam 侧逐通道按 a·x+b 拟合到原版侧后的残差（占比 >8 / 峰值）。

    拟合用整幅统计量（含透明区），对"整体调色/亮度"这类差异足够灵敏；
    只需判断残差是否塌缩，不追求精确的色彩学解释。
    """
    from PIL import Image, ImageChops, ImageStat
    mask = ImageChops.lighter(ia.split()[3], ib.split()[3]).point(lambda v: 255 if v else 0)
    n = sum(mask.histogram()[1:])
    if not n:
        return None
    fitted = []
    for cx, cy in zip(ia.convert('RGB').split(), ib.convert('RGB').split()):
        sx, sy = ImageStat.Stat(cx).sum[0], ImageStat.Stat(cy).sum[0]
        sxy = ImageStat.Stat(ImageChops.multiply(cx, cy)).sum[0]
        sx2 = ImageStat.Stat(ImageChops.multiply(cx, cx)).sum[0]
        den = n * sx2 - sx * sx
        a = (n * sxy - sx * sy) / den if den else 1.0
        b = (sy - a * sx) / n
        fitted.append(cx.point([max(0, min(255, int(round(a * v + b)))) for v in range(256)]))
    d = ImageChops.difference(Image.merge('RGB', fitted), ib.convert('RGB'))
    mx = d.split()[0]
    for c in d.split()[1:]:
        mx = ImageChops.lighter(mx, c)
    hist = ImageChops.multiply(mx, mask).histogram()
    peak = max(v for v, k in enumerate(hist) if k) if sum(hist[1:]) else 0
    return {'ratio': 100.0 * sum(hist[9:]) / n, 'peak': peak}


def _scan_display():
    """扫 asset/ 全部归档的 .WS2，建 {PNA 名: {被 0x39 选中的图层下标}}（并集）。"""
    global _DISPLAY_SCANNED, _DISPLAY_OK
    _DISPLAY_SCANNED = True
    asset = SIDES['asset']
    if not asset.exists():
        _DISPLAY_OK = False
        return
    try:
        from tool import ws2disasm
    except Exception:
        _DISPLAY_OK = False
        return
    for arc in sorted(asset.glob('*.arc')):
        try:
            data_start, index = arcstream.read_index(arc)
        except Exception:
            continue
        for raw_name, rel, size in index:
            if not raw_name.decode('utf-16le').upper().endswith('.WS2'):
                continue
            try:
                with open(arc, 'rb') as fh:
                    fh.seek(data_start + rel)
                    ins = ws2disasm.disassemble(ws2.decode(fh.read(size)))
            except Exception:
                continue
            bind = {}
            for it in ins:
                if it.opcode == 0x34:
                    try:
                        nm = it.fields['file']
                        bind[chr(it.fields['tag']) + it.fields['slot']] = nm
                        _BOUND_CACHE.add(nm.upper())
                        if nm.upper().startswith('ORG_'):        # 隔离副本 ↔ 裸名同一幅画
                            _BOUND_CACHE.add(nm[4:].upper())
                    except (TypeError, ValueError, KeyError):
                        pass
                elif it.opcode == 0x39:
                    f = bind.get(it.fields['name'])
                    if f:
                        _DISPLAY_CACHE.setdefault(f.upper(), set()).update(it.fields['frames'])
    _DISPLAY_OK = True


def _display_indices(name):
    """该资源在 asset/ 脚本里被 0x39 选中的图层下标并集。

    同时并上 `ORG_<名>` 的引用（隔离副本与裸名是同一幅画，被不同脚本引用）。
    **空集不等于"从不显示"**：事件 CG 一类不由 `0x39` 选帧，整份图层都会显示 —— 见 `_is_bound()`。
    语料不可读（asset/ 缺失或 ws2disasm 不可用） -> 返回 None（无从判断）。
    """
    if not _DISPLAY_SCANNED:
        _scan_display()
    if not _DISPLAY_OK:
        return None
    hits, found = set(), False
    for key in _aliases(name):
        if key in _DISPLAY_CACHE:
            found = True
            hits |= _DISPLAY_CACHE[key]
    return hits if found else set()


def _aliases(name):
    """该资源在脚本里可能被引用的全部名字：裸名 / `ORG_` 隔离名 / 9X 段位隔离名。

    9X 段位名只能来自 `resource/cg-conflicts.json`（项目既有约定），不按规则猜。
    """
    up = name.upper()
    out = {up, ('ORG_' + name).upper()}
    stem, _dot, ext = up.partition('.')
    base = SIZE_VARIANT_RE.sub('', stem)
    cg = cg_conflicts_map().get(base)
    if cg and cg[0]:
        out.add((cg[0] + stem[len(base):] + ('%s%s' % (_dot, ext) if _dot else '')).upper())
    return out


def _is_bound(name):
    """该资源是否被 `0x34` 绑定过（= 脚本确实在引用它，含隔离名）。"""
    if not _DISPLAY_SCANNED:
        _scan_display()
    return bool(_aliases(name) & _BOUND_CACHE)


def _rejudge_png(name, da, db):
    ia = _open_rgba(da, name, '原版')[1]
    ib = _open_rgba(db, name, 'Steam')[1]
    out = ['重判（PNG 逐像素）：原版 %s ⇄ Steam %s' % (ia.size, ib.size)]
    if ia.size != ib.size:
        a, b, note = _set_side(ia, ib)
        st = _alpha_stats(a, b)
        out.append('  ' + note)
        out.append('  归一化后：可见像素 %d，通道差 >8 占比 %.4f%%，峰值 %d，bbox %s'
                   % (st['visible'], st['rgb_ratio'], st['peak'], st['bbox']))
        out.append('  → **待定**：两侧分辨率不同，缩放本身引入误差，须人工确认后再定')
        return out, 'UNDECIDED'
    st = _alpha_stats(ia, ib)
    out.append('  同尺寸：可见像素 %d，α差 >8 占比 %.4f%%，通道差 >8 占比 %.4f%%，'
               '峰值 %d，bbox %s'
               % (st['visible'], st['alpha_ratio'], st['rgb_ratio'], st['peak'], st['bbox']))
    if st['peak'] == 0:
        out.append('  → **误报**：α 掩膜下画面完全一致（此前命中只因透明区 RGB 垃圾值'
                   '或 PNG 编码差异）')
        return out, 'FALSE'
    if st['rgb_ratio'] < NOISE_RATIO and st['peak'] <= NOISE_PEAK:
        out.append('  → **误报**：差异 %.4f%% / 峰值 %d 属重编码噪声级'
                   % (st['rgb_ratio'], st['peak']))
        return out, 'FALSE'
    res = _linear_residual(ia, ib)
    if res and res['ratio'] < GRADE_RESIDUAL:
        out.append('  线性（逐通道 a·x+b）校正后残差仅 %.4f%%（峰值 %d）→ 差异是整体调色/'
                   '亮度变体，不是不同画面；外观仍可辨，结论不变'
                   % (res['ratio'], res['peak']))
    out.append('  → **真冲突**：差异 %.4f%%（峰值 %d）超噪声级；PNG 没有"按帧选取"'
               '之说，凡引用即显示' % (st['rgb_ratio'], st['peak']))
    return out, 'REAL'


def _rejudge_pna(name, da, db):
    pa, pb = pna.load(da), pna.load(db)
    out = []
    struct_same = ((pa['canvas_w'], pa['canvas_h'], pa['layer_count'], pa['unknown'])
                   == (pb['canvas_w'], pb['canvas_h'], pb['layer_count'], pb['unknown'])
                   and [tuple(e[:9]) for e in pa['entries']]
                   == [tuple(e[:9]) for e in pb['entries']])
    out.append('重判（PNA 逐层）：canvas %dx%d %d 层 ⇄ %dx%d %d 层，逐层元数据%s'
               % (pa['canvas_w'], pa['canvas_h'], pa['layer_count'],
                  pb['canvas_w'], pb['canvas_h'], pb['layer_count'],
                  '完全一致' if struct_same else '不一致'))
    n = min(len(pa['images']), len(pb['images']))
    diffs, worst = [], None
    for i in range(n):
        xa, xb = pa['images'][i], pb['images'][i]
        if xa is None or xb is None or xa == xb:
            continue
        ia = _open_rgba(xa, '%s#层%d' % (name, i), '第 %d 层' % i)[1]
        ib = _open_rgba(xb, '%s#层%d' % (name, i), '第 %d 层' % i)[1]
        if ia.size != ib.size:
            out.append('  层 %d（lid=%s）：两侧内嵌尺寸不同 %s ⇄ %s → 待定'
                       % (i, pa['entries'][i][1], ia.size, ib.size))
            return out, 'UNDECIDED'
        st = _alpha_stats(ia, ib)
        if st['peak'] > 8:
            diffs.append(i)
            if worst is None or st['rgb_ratio'] > worst['rgb_ratio']:
                worst = st
    out.append('  实质差异层（掩膜后通道差 >8）%d / %d 层：%s'
               % (len(diffs), n, _abbrev(diffs)))
    if worst:
        out.append('  最大差层：可见像素差 >8 占比 %.4f%%，峰值 %d，bbox %s'
                   % (worst['rgb_ratio'], worst['peak'], worst['bbox']))
    if not diffs:
        out.append('  → **误报**：α 掩膜下逐层画面一致（此前命中只因透明区 RGB 垃圾值'
                   '或 PNG 编码差异）')
        return out, 'FALSE'
    if worst['rgb_ratio'] < NOISE_RATIO and worst['peak'] <= NOISE_PEAK:
        out.append('  → **误报**：差异 %.4f%% / 峰值 %d 属重编码噪声级'
                   % (worst['rgb_ratio'], worst['peak']))
        return out, 'FALSE'
    if not struct_same:
        out.append('  → **待定**：层数或逐层元数据不一致，逐层配对不可靠，须人工核'
                   '（可能是 Steam 重打包或换了素材）')
        return out, 'UNDECIDED'
    disp = _display_indices(name)
    if disp is None:
        out.append('  → **待定**：asset/ 里没有可读的脚本语料，可见性无从判断')
        return out, 'UNDECIDED'
    shown = [i for i in diffs if i in disp]
    out.append('  引用该资源（含 ORG_ 隔离名）的脚本共选中 %d 个图层下标；'
               '与差异层相交：%s' % (len(disp), _abbrev(shown) or '无'))
    if not shown:
        if not disp and _is_bound(name):
            out.append('  → **真冲突**：该资源**没有任何 `0x39` 选帧**（事件 CG 一类），'
                       '**整份图层都会显示** —— 差异层 %s 必然可见，保留原版那份（隔离名），'
                       '不可替换' % _abbrev(diffs))
            return out, 'REAL'
        out.append('  → **误报**：差异层在所有引用脚本的 `0x39` 帧中都不出现，且该资源**不是**'
                   '「无帧选择、整份显示」的类型 —— 该差异在演出中不可见，直接用 Steam 那份'
                   '（裸名，无需隔离副本）')
        return out, 'FALSE'
    out.append('  → **真冲突**：差异层 %s 会被 0x39 选中显示，改画面必被看到 —— '
               '保留原版那份（隔离名），不可替换' % _abbrev(shown))
    return out, 'REAL'


def rejudge_record(rec, da, db, info_a):
    """给一条 CONFLICT 记录补上重判结论（就地修改 rec）。"""
    if info_a['kind'] not in ('png', 'pna'):
        rec['rejudge'] = 'UNDECIDED'
        rec['rejudge_lines'] = ['非图像资源（%s）：本步只重判 PNG / PNA' % info_a['kind']]
        return rec
    try:
        if info_a['kind'] == 'png':
            lines, verdict = _rejudge_png(rec['name'], da, db)
        else:
            lines, verdict = _rejudge_pna(rec['name'], da, db)
    except ResourceError as exc:
        rec['rejudge'] = 'UNDECIDED'
        rec['rejudge_lines'] = ['重判失败（%s）→ 待定' % exc]
        return rec
    rec['rejudge'] = verdict
    rec['rejudge_lines'] = lines
    return rec


def render_rejudge_md(records):
    """重判报告：按 真冲突 / 误报 / 待定 分组，逐项给数值与依据。"""
    rows = [r for r in records if r.get('rejudge')]
    if not rows:
        return '# 同名冲突重判\n\n（本批没有 CONFLICT 项，或未加 --rejudge）\n'
    head = ['# 同名冲突重判报告', '',
            '对每条同名冲突（`CONFLICT`）做「α 掩膜下归一化像素差异 + 差异层是否被 '
            '`0x39` 选中显示」的复核，三档结论：',
            '',
            '> 判"是否被选中"时**解析隔离名别名**（脚本引用的是 `ORG_`/9X 名，只按裸名统计 `0x39`',
            '> 帧会得 0 个 → 误判成"从不显示"）；且**没有任何 `0x39` 选帧的资源（事件 CG 一类）',
            '> 整份图层都会显示**，有差异即真冲突。',
            '',
            '- **真冲突**：差异会被显示（或超噪声级）→ 必须保留原版那份（隔离名）',
            '- **误报**：差异不可见或属噪声级 → 直接用 Steam 裸名，省一份部署',
            '- **待定**：尺寸/结构不一致或语料缺失，判不了 → 人工核',
            '']
    counts = {k: sum(1 for r in rows if r['rejudge'] == k) for k in REJUDGE_LABEL}
    head += ['| 结论 | 项数 |', '|---|---|']
    for k, label in REJUDGE_LABEL.items():
        head.append('| %s | %d |' % (label, counts[k]))
    head.append('')
    for k, label in REJUDGE_LABEL.items():
        group = [r for r in rows if r['rejudge'] == k]
        head += ['', '## %s（%d 项）' % (label, len(group)), '']
        if not group:
            head.append('（无）')
            continue
        for r in sorted(group, key=lambda x: x['name'].upper()):
            head.append('### `%s`' % r['name'])
            head.append('')
            head.append('归档 原版 %s ⇄ Steam %s；字节 %s ⇄ %s；隔离判定 %s'
                        % (r['arc'] or '-', r['alt_arc'] or '-', human(r['size'] or 0),
                           human(r['alt_size'] or 0),
                           ISOLATION_LABEL.get(r.get('isolation'), '（未判定）')))
            head.append('')
            for line in r.get('rejudge_lines') or []:
                head.append('- %s' % line)
            if r.get('isolation_name'):
                head.append('- 隔离名 `%s`%s'
                            % (r['isolation_name'],
                               ('（已存在于 asset/%s）' % r['isolation_arc'])
                               if r.get('isolation_arc') else '（尚未部署）'))
            head.append('')
    return '\n'.join(head) + '\n'


def cross_scan(records):
    """找"名字不同、内容相同"的反直觉项：原版某名 ⇄ Steam 另一个名。

    两侧同名不同内容的（CONFLICT）不在其中；这里要的是**不同名却同内容**——
    命中就意味着可以少部署一份，直接引用 Steam 那个名字。
    只在本批次已比对的资源名之间找（不做全归档扫描，那代价是 O(归档体积)）。
    """
    jp_by_key, alt_by_key = {}, {}
    for r in records:
        if not r['_keys']:
            continue
        ja, sb, jsha, ssha = r['_keys']
        if ja is not None:
            jp_by_key.setdefault(ja, []).append((r['name'], jsha))
        if sb is not None:
            alt_by_key.setdefault(sb, []).append((r['name'], ssha))
    hits, seen = [], set()
    for key, a_list in jp_by_key.items():
        for b_list in [alt_by_key.get(key, [])]:
            for a, asha in a_list:
                for b, bsha in b_list:
                    if a.upper() == b.upper() or (a.upper(), b.upper()) in seen:
                        continue
                    seen.add((a.upper(), b.upper()))
                    hits.append((a, b, asha == bsha))
    for r in records:
        if not r['_keys']:
            continue
        for a, b, _s in hits:
            if r['name'].upper() == a.upper():
                r['dup'] = b
    return hits


def suggest_renames(records, taken, deployed=None, ref=None, use_conflict_map=True):
    """按项目既有规则给出改名候选（只写进报告，不动任何文件）。

    立绘（st* 槽，`Aひかり_02L` 式）→ `ORG_` 前缀；
    事件 CG（ev* 槽，`HIK_09L` 式）→ **先查 `resource/cg-conflicts.json` 的既有映射**，
    查不到才退回 `[ROUTE]_9X[L/S]` 段位扫描（ev 槽 stem ≤7 字节），
    同一 (路线, 编号) 的 L/S 整对用同一个 9X 段位；其余给 `ORG_` 前缀候选并标注
    "槽位长度限制未验证"。候选名若已被占用，会顺带按格式验内容，查"已部署的那一份
    是不是就是原版内容"（不只看字节）。`use_conflict_map=False` 时退回增补前的行为。
    """
    groups = {}
    for r in records:
        if r['verdict'] != 'CONFLICT':
            continue
        base, ext = Path(r['name']).stem, Path(r['name']).suffix.upper()
        if CG_RE.match(base):
            # `HIK_09L` -> ('HIK', '09') / 'L'（编号 2 位；旧版 base[3:5]/base[5:] 错位，
            # 该分支在本项目里从未被真实触发过，故一直没暴露）
            groups.setdefault((base[:3], base[4:6]), {})[base[6:]] = (r, ext)
    for (route, num), variants in sorted(groups.items()):
        mapped = cg_conflicts_map().get('%s_%s' % (route, num)) if use_conflict_map else None
        if mapped is not None:
            patch = mapped[0]
            for v, (r, ext) in variants.items():
                r['suggest'] = '%s%s%s' % (patch, v, ext)
                r['suggest_reason'] = ('事件 CG：沿用 resource/cg-conflicts.json 的既有映射 '
                                       '%s_%s→%s（不按命名规则猜 9X 段位）'
                                       % (route, num, patch))
            continue
        for x in range(90, 100):
            if any(('%s_%d%s' % (route, x, v)).upper() in taken for v in variants):
                continue
            for v, (r, ext) in variants.items():
                r['suggest'] = '%s_%d%s%s' % (route, x, v, ext)
                r['suggest_reason'] = ('事件 CG 走 ev01/ev02 槽，stem 限 ≤7 字节，'
                                       '故用 9X 段位；同 (路线,编号) 的变体整对同段位；'
                                       '⚠ cg-conflicts.json 里没有该映射，此处为扫描候选，'
                                       '落库前应补进映射表')
            break
    for r in records:
        if r['verdict'] != 'CONFLICT' or r['suggest']:
            continue
        base, ext = Path(r['name']).stem, Path(r['name']).suffix.upper()
        if CG_RE.match(base):
            r['suggest_reason'] = '事件 CG 但 90–99 段位已排满——需人工另择方案'
            continue
        cand = 'ORG_' + base + ext
        if PORTRAIT_RE.match(base):
            r['suggest_reason'] = '立绘走 st* 槽，接受 ORG_ 前缀 + 日文名（已实测通过）'
        else:
            r['suggest_reason'] = ('非立绘资源：ORG_ 前缀为候选方案，'
                                   '该槽位的名称长度限制尚未实测')
        if cand.upper() in taken:
            r['suggest_reason'] += '；' + _occupant_note(deployed, cand, r, ref)
        r['suggest'] = cand
    # 有既有约定时，候选名一律用约定给的**原文**（保留归档里的原始大小写），
    # 与"隔离判定"节给出的名字保持一致，避免抄错大小写
    for r in records:
        if r.get('isolation_name'):
            r['suggest'] = r['isolation_name']


def _occupant_note(deployed, cand, rec, ref=None):
    """候选名已被占用时，查占位者是不是"就是原版那一份"（按格式验内容，不只看字节）。

    `ref is None`（--no-isolation-check）时退回增补前的字节级判定，保证输出逐字不变。
    """
    if deployed is None:
        return '⚠ 候选名已被占用，需人工确认占位内容'
    if ref is None:
        try:
            data, _arc, _orig = deployed.fetch(cand)
        except ResourceError:
            return '⚠ 候选名已被占用，且无法读取占位成员'
        jp_sha = (rec.get('_keys') or (None, None, None, None))[2]
        if jp_sha and sha(data) == jp_sha:
            rec['suggest_reused'] = True
            return '该名已存在于 asset/ 且内容与原版逐字节相同 → 可直接复用，无需新增部署'
        return '⚠ 候选名已被占用（内容与原版不同），需人工另择名'
    try:
        iso_info, iso_raw = deployed.load(cand)
        jp_info, jp_raw = ref.load(rec['name'])
    except ResourceError:
        return '⚠ 候选名已被占用，且无法读取占位成员'
    same, _sub = evidence(jp_info, iso_info, jp_raw, iso_raw)
    if same:
        rec['suggest_reused'] = True
        return ('该名已存在于 asset/%s 且按「%s」判据内容 == 原版 → 可直接复用，无需新增部署'
                % (iso_info['arc'], KIND_LABEL.get(jp_info['kind'], jp_info['kind'])))
    return ('⚠ 候选名已被占用，且占位内容 **!= 原版**（错配，见"隔离判定"节）→ '
            '需人工核对后重新部署，不要直接引用')


# --------------------------------------------------------------------------
# 输入
# --------------------------------------------------------------------------
def load_names(args, ref, alt):
    items, seen = [], set()

    def add(name, hint=None):
        if ':' in name:
            hint, name = name.split(':', 1)
        key = (name.upper(), (hint or '').upper())
        if key not in seen:
            seen.add(key)
            items.append((name, hint))

    for n in args.names:
        add(n)
    if args.names_file:
        text = Path(args.names_file).read_text(encoding='utf-8')
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith('#'):
                add(line)
    if args.seam:
        s, o = args.seam
        for n in names_in_script(alt, s):
            add(n)
        for n in names_in_script(ref, o):
            add(n)
    if args.script:
        side = Side(args.script_side, SIDES[args.script_side])
        for n in names_in_script(side, args.script):
            add(n)
    if args.arc:
        for side in (ref, alt):
            for arc, _rel, _sz, orig in side.index().values():
                if arc.upper() == args.arc.upper():
                    add(orig, args.arc)
    if not items:
        raise SystemExit('没有可比对的资源名：给位置参数 / --names-file / --arc / --seam 之一')
    if args.limit:
        items = items[:args.limit]
    return items


# --------------------------------------------------------------------------
# 输出
# --------------------------------------------------------------------------
ORDER = {'CONFLICT': 0, 'STEAM_MISSING': 1, 'ABSENT_BOTH': 2, 'ERROR': 3,
         'SAME': 4, 'JP_MISSING': 5}
# --isolation-verdicts 提升为主 verdict 后的排序（错配最前，已处理后置）
ISO_ORDER = {'ISOLATION_MISMATCH': 0, 'NEEDS_ISOLATION': 0, 'CONFLICT': 0,
             'STEAM_MISSING': 1, 'ABSENT_BOTH': 2, 'ERROR': 3, 'HANDLED': 4,
             'SAME': 5, 'JP_MISSING': 6}


def _sort_key(r):
    """报告排序：默认与增补前一致（按 verdict 分组、组内按名）。"""
    v = r['verdict']
    if v in ORDER:
        return (ORDER[v], r['name'].upper())
    return (ISO_ORDER.get(v, 9), r['name'].upper())


def summary_line(records):
    """一行汇总；同名冲突项额外按隔离判定细分，便于一眼看出"还要不要新增部署"。"""
    counts = {}
    for r in records:
        counts[r['verdict']] = counts.get(r['verdict'], 0) + 1
    parts = ['%s %d' % (VERDICT_LABEL[k], v) for k, v in sorted(counts.items())]
    iso = {}
    for r in records:
        if r.get('isolation'):
            iso[r['isolation']] = iso.get(r['isolation'], 0) + 1
    if iso:
        parts.append('其中同名冲突的隔离判定：%s'
                     % '，'.join('%s %d' % (ISOLATION_LABEL[k], v)
                                 for k, v in sorted(iso.items())))
    return '共 %d 项：%s' % (len(records), '，'.join(parts)) + '\n'


def iso_cell(r):
    """主表"隔离"列：这个同名冲突到底要不要新增部署。"""
    if not r.get('isolation'):
        return '—'
    label = ISOLATION_LABEL[r['isolation']]
    if r['isolation'] == 'HANDLED':
        return '**已处理** → 引用 `%s`' % r.get('isolation_name')
    if r['isolation'] == 'NEEDS_ISOLATION':
        need = r.get('isolation_name')
        return ('**未处理** → 需补 `%s`（%s）' % (need, r.get('isolation_target') or '归档待定')
                if need else '**未处理**（无既有约定，需人工定名）')
    return '**⚠ 隔离错配（错误级）** `%s`' % r.get('isolation_name')


def render_md(records, dups, name_rows=()):
    mism = [r for r in records if r.get('isolation') == 'ISOLATION_MISMATCH']
    out = []
    if mism:
        out += ['> ⚠ **隔离错配 %d 项（错误级）**：隔离副本已存在但内容 != 原版——'
                '引擎不报错、只会画面错乱（doc/lessons-learned.md 第五类缺陷）。'
                '必须人工核对后重新部署，切勿直接引用：%s'
                % (len(mism), ', '.join('`%s`' % r['name'] for r in mism)), '']
    out += [summary_line(records).rstrip('\n'), '']
    # 没有任何隔离判定时（例如 --no-isolation-check），表格与增补前逐字一致
    show_iso = any(r.get('isolation') for r in records)
    cols = ['#', '资源名', '原版归档', 'Steam 归档', '结论']
    if show_iso:
        cols.append('隔离判定')
    cols.append('摘要')
    out += ['| ' + ' | '.join(cols) + ' |', '|' + '---|' * len(cols)]
    for i, r in enumerate(sorted(records, key=_sort_key), 1):
        cells = [str(i), '`%s`' % r['name'], r['arc'] or '—', r['alt_arc'] or '—',
                 '**%s**' % VERDICT_LABEL[r['verdict']]]
        if show_iso:
            cells.append(iso_cell(r))
        cells.append((r['evidence'][0] if r['evidence'] else '').replace('|', '/'))
        out.append('| %s |' % ' | '.join(cells))
    out.append('')
    iso_recs = [r for r in records if r.get('isolation')]
    if iso_recs:
        out += ['### 隔离判定（同名冲突项：已处理 / 未处理 / 错配）', '',
                '| 冲突名 | 判定 | 隔离名 | 隔离副本位置 | 目标归档 | 依据 |',
                '|---|---|---|---|---|---|']
        for r in sorted(iso_recs, key=lambda x: (ISO_ORDER.get(x['isolation'], 9),
                                                 x['name'].upper())):
            out.append('| `%s` | **%s** | %s | %s | %s | %s |'
                       % (r['name'], ISOLATION_LABEL[r['isolation']],
                          '`%s`' % r['isolation_name'] if r.get('isolation_name') else '—',
                          r.get('isolation_arc') or '—',
                          r.get('isolation_target') or '—',
                          (r.get('isolation_rule') or '').replace('|', '/')))
        out.append('')
        handled = [r for r in iso_recs if r['isolation'] == 'HANDLED']
        need = [r for r in iso_recs if r['isolation'] == 'NEEDS_ISOLATION']
        out += ['- **零新增**（已处理，直接引用隔离名）：%s'
                % ('、'.join('`%s` → `%s`' % (r['name'], r['isolation_name'])
                            for r in handled) or '无'),
                '- **需新增部署**（未处理）：%s'
                % ('、'.join('`%s` ⇐ 原版 `%s`'
                            % (r.get('isolation_name') or '？需人工定名', r['name'])
                            for r in need) or '无'),
                '- **错配（错误级）**：%s'
                % ('、'.join('`%s`' % r['name'] for r in mism) or '无'), '']
    if name_rows:
        out += ['### 脚本引用名序列差异（两侧都在引用资源、但引用的名字不同）', '',
                '| 类型 | 原版引用 | Steam 引用 |', '|---|---|---|']
        for row in name_rows:
            out.append('| %s | %s | %s |'
                       % (row['kind'], ', '.join('`%s`' % n for n in row['ref']) or '—',
                          ', '.join('`%s`' % n for n in row['alt']) or '—'))
        out.append('')
    if dups:
        out += ['### 跨名同内容（文件名不同、内容相同）', '',
                '| 原版名 | Steam 名 | 字节是否也相同 |', '|---|---|---|']
        for a, b, strict in dups:
            out.append('| `%s` | `%s` | %s |' % (a, b, '是' if strict else '否（仅判据键相同）'))
        out.append('')
    sugg = [r for r in records if r.get('suggest')]
    if sugg:
        out += ['### 隔离建议（改名候选，仅供参考，未写入任何文件）', '',
                '| 冲突名 | 改名候选 | 依据 |', '|---|---|---|']
        for r in sugg:
            out.append('| `%s` | `%s` | %s |' % (r['name'], r['suggest'], r['suggest_reason']))
        out.append('')
    out += ['### 逐项证据', '']
    for r in sorted(records, key=_sort_key):
        head = '#### `%s` — %s' % (r['name'], VERDICT_LABEL[r['verdict']])
        if r.get('isolation'):
            head += '／隔离判定：%s' % ISOLATION_LABEL[r['isolation']]
        out.append(head)
        out += ['- %s' % e for e in r['evidence']]
        if r.get('isolation_name'):
            out.append('- 隔离名：`%s`%s' % (
                r['isolation_name'],
                '（已部署于 asset/%s）' % r['isolation_arc'] if r.get('isolation_arc')
                else '（待部署到 %s）' % (r.get('isolation_target') or '归档待定')))
        if r.get('isolation_rule'):
            out.append('- 隔离名依据：%s' % r['isolation_rule'])
        if r.get('suggest'):
            out.append('- 隔离建议：`%s`（%s）' % (r['suggest'], r['suggest_reason']))
        if r.get('dup'):
            out.append('- 跨名同内容：内容等于 Steam 的 `%s`' % r['dup'])
        out.append('')
    return '\n'.join(out)


def render_isolation_md(records):
    """只出隔离判定小节（"还要新增部署什么"的最小清单）。"""
    iso_recs = [r for r in records if r.get('isolation')]
    mism = [r for r in iso_recs if r['isolation'] == 'ISOLATION_MISMATCH']
    out = []
    if mism:
        out += ['> ⚠ **隔离错配 %d 项（错误级）**：%s'
                % (len(mism), ', '.join('`%s`' % r['name'] for r in mism)), '']
    if not iso_recs:
        return '本批次没有同名冲突项，无需隔离判定。\n'
    counts = {}
    for r in iso_recs:
        counts[r['isolation']] = counts.get(r['isolation'], 0) + 1
    out += ['共有同名冲突 %d 项：%s' % (len(iso_recs), '，'.join(
        '%s %d' % (ISOLATION_LABEL[k], counts[k])
        for k in sorted(counts, key=lambda k: ISO_ORDER.get(k, 9)))), '']
    out += ['| 冲突名 | 判定 | 隔离名 | 隔离副本位置 | 目标归档 |',
            '|---|---|---|---|---|']
    for r in sorted(iso_recs, key=lambda x: (ISO_ORDER.get(x['isolation'], 9),
                                             x['name'].upper())):
        out.append('| `%s` | **%s** | %s | %s | %s |'
                   % (r['name'], ISOLATION_LABEL[r['isolation']],
                      '`%s`' % r['isolation_name'] if r.get('isolation_name') else '—',
                      r.get('isolation_arc') or '—',
                      r.get('isolation_target') or '—'))
    out += ['', '**需新增部署（未处理）**：%s'
            % ('、'.join('原版 `%s` → `%s`（%s）'
                         % (r['name'], r.get('isolation_name') or '？需人工定名',
                            r.get('isolation_target') or '归档待定')
                         for r in iso_recs if r['isolation'] == 'NEEDS_ISOLATION') or '无'),
            '**零新增（已处理，直接引用隔离名）**：%s'
            % ('、'.join('`%s` ← `%s`' % (r['isolation_name'], r['name'])
                         for r in iso_recs if r['isolation'] == 'HANDLED') or '无'), '']
    return '\n'.join(out)


def render_csv(records):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator='\n')
    w.writerow(['name', 'verdict', 'jp_archive', 'jp_bytes', 'steam_archive', 'steam_bytes',
                'evidence', 'rename_candidate',
                # 增补列（追加在末尾，既有列的语义与顺序不变）
                'isolation', 'isolation_name', 'isolation_arc', 'isolation_target',
                'isolation_rule'])
    for r in records:
        w.writerow([r['name'], r['verdict'], r['arc'] or '', r['size'] or '',
                    r['alt_arc'] or '', r['alt_size'] or '',
                    ' ; '.join(r['evidence']), r['suggest'] or '',
                    r.get('isolation') or '', r.get('isolation_name') or '',
                    r.get('isolation_arc') or '', r.get('isolation_target') or '',
                    r.get('isolation_rule') or ''])
    return buf.getvalue()


def main():
    ap = argparse.ArgumentParser(description='日文原版 vs Steam 基线 的资源内容级比对')
    ap.add_argument('names', nargs='*', help='资源名，可写 `归档名:成员名` 限定归档')
    ap.add_argument('--names-file', help='每行一个资源名的清单文件（UTF-8，# 为注释）')
    ap.add_argument('--arc', help='枚举该归档两边的全部成员逐个比对')
    ap.add_argument('--seam', nargs=2, metavar=('ALT_STEM', 'REF_STEM'),
                    help='拿两侧脚本引用到的资源名作为清单')
    ap.add_argument('--script', help='只从一段脚本提取资源名')
    ap.add_argument('--script-side', default=REF, choices=sorted(SIDES),
                    help='--script 的取用侧（默认 %s）' % REF)
    ap.add_argument('--limit', type=int, help='最多比对多少项（--arc 大归档时用）')
    ap.add_argument('--cross-scan', action='store_true', help='找名字不同、内容相同的项')
    ap.add_argument('--suggest-rename', action='store_true', help='对同名冲突给出改名候选')
    ap.add_argument('--no-isolation-check', action='store_true',
                    help='不做"同名冲突是否已处理"判定（输出与增补前一致）')
    ap.add_argument('--isolation-verdicts', action='store_true',
                    help='把隔离子判定（HANDLED/NEEDS_ISOLATION/ISOLATION_MISMATCH）'
                         '提升为主 verdict，便于按 verdict 过滤；默认只作子判定字段')
    ap.add_argument('--isolation-summary-only', action='store_true',
                    help='只打印隔离判定小节（配合 --format md，用于快速看"还要新增什么"）')
    ap.add_argument('--rejudge', action='store_true',
                    help='对每条同名冲突做像素级复核（α 掩膜归一化差异 + 差异层是否被 '
                         '0x39 显示），给出 真冲突/误报/待定 三档；md 输出切到重判报告')
    ap.add_argument('--max-pixels', type=int, default=MAX_PIXELS,
                    help='单幅图像素上限（默认 %d）' % MAX_PIXELS)
    ap.add_argument('--format', default='md', choices=('md', 'csv', 'json'))
    ap.add_argument('-o', '--output', help='写入文件（默认打到 stdout）')
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    globals()['MAX_PIXELS'] = args.max_pixels
    globals()['REJUDGE'] = args.rejudge

    ref, alt = Side(REF, SIDES[REF]), Side(ALT, SIDES[ALT])
    seq_ref = seq_alt = None
    if args.seam:
        seq_alt = names_in_script(alt, args.seam[0])
        seq_ref = names_in_script(ref, args.seam[1])
    items = load_names(args, ref, alt)
    asset = None
    if not args.no_isolation_check or args.suggest_rename:
        asset = Side('asset', SIDES['asset'])
    iso_ref = None if args.no_isolation_check else ref
    records = []
    for i, (name, hint) in enumerate(items, 1):
        if len(items) > 20:
            print('[%d/%d] %s' % (i, len(items), name), file=sys.stderr)
        records.append(compare(name, hint, ref, alt, asset if iso_ref else None))

    dups = cross_scan(records) if args.cross_scan else []
    name_rows = name_sequence_diff(seq_ref, seq_alt) if seq_ref is not None else []
    if args.suggest_rename:
        taken = set(ref.index()) | set(alt.index()) | set(asset.index())
        suggest_renames(records, taken, asset, iso_ref,
                        use_conflict_map=not args.no_isolation_check)
    if args.isolation_verdicts:
        for r in records:
            if r.get('isolation'):
                r['verdict'] = r['isolation']
                r['verdict_base'] = 'CONFLICT'

    if args.format == 'md':
        if args.isolation_summary_only:
            text = render_isolation_md(records)
        elif args.rejudge:
            text = render_rejudge_md(records)
        else:
            text = render_md(records, dups, name_rows)
    elif args.format == 'csv':
        text = render_csv(records)
    else:
        text = json.dumps([{k: v for k, v in r.items() if not k.startswith('_')}
                           for r in records], ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding='utf-8')
        print('已写入 %s（%d 项）' % (args.output, len(records)))
    else:
        print(text)

    errors = [r for r in records if r['verdict'] == 'ERROR']
    if errors:
        print('有 %d 项解析失败：%s'
              % (len(errors), ', '.join(r['name'] for r in errors)), file=sys.stderr)
        return 2
    mism = [r for r in records if r.get('isolation') == 'ISOLATION_MISMATCH']
    if mism:
        print('⚠ 隔离错配 %d 项（错误级，隔离副本内容 != 原版）：%s'
              % (len(mism), ', '.join(r['name'] for r in mism)), file=sys.stderr)
        return 3
    return 0


if __name__ == '__main__':
    sys.exit(main())
