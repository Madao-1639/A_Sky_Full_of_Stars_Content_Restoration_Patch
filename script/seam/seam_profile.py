"""Per-seam profile: how BIG is the Steam rewrite, and which 演出 does it span.

Baseline = the original Japanese 2015 archive (bare names, incl. the 17 *_H).
Steam side = asset/Rio.arc *_E.

Alignment anchors on the VOICE track (the *.OGG name loaded just before each line):
the project assumes voice and text agree semantically, so a line whose voice file
matches the original's is treated as unchanged and never compared textually. That
drops the whole re-translation class (Steam re-worded the English) and removes any
need to read a second build's text.

Scope limit: this validates 台词 only. 旁白 carries no voice, so two different
narration lines are indistinguishable to this method -- 旁白 is therefore compared
by COUNT between 台词 anchors, and its content is reported as unverified rather
than as "same".

What the report gives per differing region: 句数 on both sides, the source index
range, and the full 演出 inventory spanned by the region (CG slots, 立绘 slots,
backgrounds, transitions, masks, BGM, voices).

Usage:
  python script/seam/seam_profile.py <steam_stem> <orig_stem>      # one neighbour pair
  python script/seam/seam_profile.py --md                          # all seams, grouped by scene
"""
import difflib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from tool import arcbuild, lng, ws2                                    # noqa: E402
from script.probe.ws2_events import PNA, RES, TEXT                                  # noqa: E402

JP = ROOT.parent / '抬头看看吧看那天上的繁星' / 'Rio.arc'
PATHS = {'asset': ROOT / 'asset' / 'Rio.arc', 'zh': ROOT / 'asset' / 'zh-CN' / 'Rio.arc',
         'backup': ROOT / 'backup' / 'Rio.arc', 'jp': JP}

_cache = {}


def blob(side, name):
    if side not in _cache:
        _cache[side] = {n.decode('utf-16le').upper(): d for n, d in arcbuild.read_raw(PATHS[side])}
    return _cache[side].get(name.upper())


def classify(name, slot=None):
    if slot is not None:
        return 'CG' if slot.startswith('ev') else '立绘'
    n = name.upper()
    if n.endswith('.OGG'):
        return 'BGM' if n.startswith('BGM') else '语音'
    if 'MSK' in n:
        return '遮罩'
    if n.startswith('EFBG'):
        return '转场'
    if n.startswith('SKY'):
        return '天空'
    if n.startswith('BG_'):
        return '背景'
    if n.startswith('EST_'):
        return '静帧'
    if n.startswith('CUTIN'):
        return '过场'
    return '其他图像'


def walk(side, stem):
    """[{idx, text, gap, slots, zh}] -- one entry per text record."""
    raw = blob(side, stem.upper() + '.WS2')
    if raw is None:
        raise SystemExit('%s: %s 不存在' % (side, stem))
    data = ws2.decode(raw)
    spans = [m.span() for m in TEXT.finditer(data)]
    zh = []
    if side == 'asset':
        zraw = blob('zh', stem.upper() + '.LNG')
        zh = lng.parse_lng(zraw) if zraw else []
    evs = []
    for m in TEXT.finditer(data):
        evs.append((m.start(), 'text', (int.from_bytes(m.group(1), 'little'),
                                        m.group(3).decode('shift_jis', 'replace'))))
    for rx, kind, fn in ((PNA, 'pna', lambda m: (m.group(1).decode('ascii', 'replace'),
                                                 m.group(2).decode('shift_jis', 'replace'))),
                         (RES, 'res', lambda m: m.group(1).decode('shift_jis', 'replace'))):
        for m in rx.finditer(data):
            if any(x <= m.start() < y for x, y in spans):
                continue
            evs.append((m.start(), kind, fn(m)))
    evs.sort(key=lambda e: e[0])
    slots, gap, out = {}, [], []
    for pos, kind, payload in evs:
        if kind == 'pna':
            slots[payload[0]] = payload[1]
        elif kind == 'res':
            gap.append(payload)
        else:
            idx, text = payload
            out.append({'idx': idx, 'text': text, 'gap': gap, 'slots': dict(slots),
                        'zh': zh[idx] if 0 <= idx < len(zh) else None})
            gap = []
    return out


def voices(rec):
    return tuple(sorted(v for v in rec['gap']
                        if v.upper().endswith('.OGG') and not v.upper().startswith('BGM')))


def units(records):
    """One entry per VOICED record -- the 台词 anchors -- each carrying the number
    of UNVOICED records that precede it, plus a trailing unit for a closing
    unvoiced run.

    The voice track says nothing about unvoiced lines: narration, and the
    protagonist's own lines (Akito has no voice actor), carry no OGG, so two
    different such lines look identical to this method. Anchoring on voiced 台词
    and comparing the unvoiced COUNT in between is the most the voice track can
    support; a same-count rewrite of an unvoiced line stays invisible (see the
    caveat in doc/pending-issues.md 问题 2)."""
    out, pending = [], 0
    for i, r in enumerate(records):
        vs = voices(r)
        if vs:
            out.append({'voice': vs, 'narr': pending, 'pos': i})
            pending = 0
        else:
            pending += 1
    out.append({'voice': (), 'narr': pending, 'pos': len(records)})
    return out


def narr_range(records, unit):
    """(lo, hi) of the unvoiced records attached to a unit."""
    return (unit['pos'] - unit['narr'], unit['pos'])


def inventory(records, lo, hi):
    inv = {}
    for r in records[lo:hi]:
        for slot, name in r['slots'].items():
            inv.setdefault(classify(name, slot), set()).add('%s=%s' % (slot, name))
        for name in r['gap']:
            inv.setdefault(classify(name), set()).add(name)
    return inv


def inv_str(inv):
    if not inv:
        return '无'
    return '；'.join('%s %d: %s' % (k, len(v), ', '.join(sorted(v)[:8]))
                     for k, v in sorted(inv.items()))


def rng(lo, hi):
    return '%d–%d' % (lo, hi - 1) if hi > lo else '—'


def regions(stem_s, stem_o):
    """(records_steam, records_orig, units_steam, units_orig, opcodes).

    The opcodes align the 台词 (voiced) sequences only -- 旁白 carries no voice, so
    it cannot be matched by this method and instead rides inside each unit as a
    count."""
    s = walk('asset', stem_s)
    o = walk('jp', stem_o)
    us, uo = units(s), units(o)
    ops = difflib.SequenceMatcher(None, [u['voice'] for u in uo],
                                  [u['voice'] for u in us], autojunk=False).get_opcodes()
    return s, o, us, uo, ops


def span(records, unit_list, lo, hi):
    """Record index range [lo, hi) covered by unit_list[lo:hi]."""
    if hi <= lo:
        return (unit_list[lo]['pos'], unit_list[lo]['pos'])
    start = narr_range(records, unit_list[lo])[0]
    last = unit_list[hi - 1]
    end = last['pos'] if not last['voice'] else last['pos'] + 1
    return (start, min(end, len(records)))


def counts(unit_list, lo, hi):
    """(台词 数, 旁白 数) over unit_list[lo:hi]."""
    return (sum(1 for u in unit_list[lo:hi] if u['voice']),
            sum(u['narr'] for u in unit_list[lo:hi]))


def _lines(records, lo, hi, samples, prefix):
    out = []
    for k in range(min(hi - lo, samples)):
        r = records[lo + k]
        out.append('%s[%d]　%s' % (prefix, r['idx'],
                                   (r['zh'] or r['text'])[:70].replace('\\n', '⏎')))
    if hi - lo > samples:
        out.append('%s…… 其余 %d 句略' % (' ' * len(prefix.rstrip()), hi - lo - samples))
    return out


def profile(stem_s, stem_o, samples=3):
    s, o, us, uo, ops = regions(stem_s, stem_o)
    sl, sn = counts(us, 0, len(us))
    ol, on = counts(uo, 0, len(uo))
    out = ['- **规模**：Steam %d 句（台词 %d + 旁白 %d）/ 原版 %d 句（台词 %d + 旁白 %d）（Δ%+d）'
           % (len(s), sl, sn, len(o), ol, on, len(s) - len(o))]
    changed = False
    for tag, i1, i2, j1, j2 in ops:
        if tag == 'equal':
            # 台词逐条对应；再比对夹在同一条台词前后的旁白句数
            for k in range(i2 - i1):
                a, b = uo[i1 + k], us[j1 + k]
                if a['narr'] == b['narr']:
                    continue
                changed = True
                alo, ahi = narr_range(o, a)
                blo, bhi = narr_range(s, b)
                out.append('- **旁白句数不同**（位于同一条台词 %s 之前）：原版 idx %s（%d 句）⇄ Steam idx %s（%d 句）'
                           % (a['voice'][0] if a['voice'] else '（结尾）', rng(alo, ahi), a['narr'],
                              rng(blo, bhi), b['narr']))
                out.append('  - 原版侧演出：%s' % inv_str(inventory(o, alo, ahi)))
                out.append('  - Steam 侧演出：%s' % inv_str(inventory(s, blo, bhi)))
                out += ['  - ' + t for t in _lines(o, alo, ahi, samples, ' 原版')]
                out += ['    ' + t for t in _lines(s, blo, bhi, samples, 'Steam')]
            continue
        changed = True
        label = {'replace': '台词不同', 'delete': '原版有 / Steam 删',
                 'insert': 'Steam 新增'}[tag]
        olo, ohi = span(o, uo, i1, i2)
        slo, shi = span(s, us, j1, j2)
        ocl, ocn = counts(uo, i1, i2)
        scl, scn = counts(us, j1, j2)
        out.append('- **%s**：原版 idx %s（台词 %d + 旁白 %d）⇄ Steam idx %s（台词 %d + 旁白 %d）'
                   % (label, rng(olo, ohi), ocl, ocn, rng(slo, shi), scl, scn))
        if ohi > olo:
            out.append('  - 原版侧演出：%s' % inv_str(inventory(o, olo, ohi)))
        if shi > slo:
            out.append('  - Steam 侧演出：%s' % inv_str(inventory(s, slo, shi)))
        out += ['  - ' + t for t in _lines(o, olo, ohi, samples, ' 原版')]
        out += ['    ' + t for t in _lines(s, slo, shi, samples, 'Steam')]
    if not changed:
        out.append('- 台词一一对应，无语音句（旁白／男主台词）句数也一致 → 无差异'
                   '（注：无语音句的**内容**无法用语音判定）')
    return '\n'.join(out)


SEAMS = [
    ('yozora_hika_103d_H', [('入口', 'yozora_hika_103c_E', 'yozora_hika_103c'),
                            ('出口', 'yozora_hika_103e_E', 'yozora_hika_103e')]),
    ('yozora_hika_103f', [('入口', 'yozora_hika_103e_E', 'yozora_hika_103e')]),
    ('yozora_hika_103g_H', [('出口', 'yozora_hika_103h_E', 'yozora_hika_103h')]),
    ('yozora_hika_108g_H', [('入口', 'yozora_hika_108f_E', 'yozora_hika_108f'),
                            ('出口', 'yozora_hika_108h_E', 'yozora_hika_108h')]),
    ('yozora_hika_110c_H', [('入口', 'yozora_hika_110b_E', 'yozora_hika_110b'),
                            ('出口', 'yozora_hika_110d_E', 'yozora_hika_110d')]),
    ('yozora_saya_101j_H', [('入口', 'yozora_saya_101i_E', 'yozora_saya_101i'),
                            ('出口', 'yozora_saya_102_E', 'yozora_saya_102')]),
    ('yozora_saya_102c_H', [('入口', 'yozora_saya_102b_E', 'yozora_saya_102b'),
                            ('出口', 'yozora_saya_102d_E', 'yozora_saya_102d')]),
    ('yozora_saya_107b_H', [('入口', 'yozora_saya_107a_E', 'yozora_saya_107a'),
                            ('出口', 'yozora_saya_107c_E', 'yozora_saya_107c')]),
    ('yozora_saya_107d_H', [('出口', 'yozora_saya_107e_E', 'yozora_saya_107e')]),
    ('yozora_ori_115_H', [('入口', 'yozora_ori_114b_E', 'yozora_ori_114b'),
                          ('出口', 'yozora_ori_116_E', 'yozora_ori_116')]),
    ('yozora_ori_117b', [('入口', 'yozora_ori_117a_E', 'yozora_ori_117a')]),
    ('yozora_ori_118_H', [('出口', 'yozora_ori_119_E', 'yozora_ori_119')]),
    ('yozora_ori_123_H', [('入口', 'yozora_ori_122b_E', 'yozora_ori_122b'),
                          ('出口', 'yozora_ori_124_E', 'yozora_ori_124')]),
    ('yozora_ori_129_H', [('入口', 'yozora_ori_128c_E', 'yozora_ori_128c'),
                          ('出口', 'yozora_ori_130_E', 'yozora_ori_130')]),
    ('yozora_koro_115_H', [('入口', 'yozora_koro_114b_E', 'yozora_koro_114b'),
                           ('出口', 'yozora_koro_116_E', 'yozora_koro_116')]),
    ('yozora_koro_121_H', [('入口', 'yozora_koro_120_E', 'yozora_koro_120'),
                           ('出口', 'yozora_koro_122_E', 'yozora_koro_122')]),
    ('yozora_koro_124_H', [('入口', 'yozora_koro_123a_E', 'yozora_koro_123a'),
                           ('出口', 'yozora_koro_125_E', 'yozora_koro_125')]),
    ('yozora_koro_126_H', [('入口', 'yozora_koro_125b_E', 'yozora_koro_125b')]),
    ('yozora_koro_127', [('出口', 'yozora_koro_128_E', 'yozora_koro_128')]),
    ('yozora_koro_131_H', [('入口', 'yozora_koro_130_ep1_E', 'yozora_koro_130_ep1'),
                           ('出口', 'yozora_koro_132_ep2_E', 'yozora_koro_132_ep2')]),
]


def emit_md():
    for scene, neighbours in SEAMS:
        print('\n#### %s\n' % scene)
        for role, stem_s, stem_o in neighbours:
            print('**%s**　`%s` ⇄ 原版 `%s`\n' % (role, stem_s, stem_o))
            print(profile(stem_s, stem_o))
            print()


def show(stem_s, stem_o):
    s, o, _us, _uo, _ops = regions(stem_s, stem_o)
    print('=' * 100)
    print('%s  (Steam %d 句)   ←→   原版 %s  (JP %d 句)   Δ%+d' %
          (stem_s, len(s), stem_o, len(o), len(s) - len(o)))
    print('=' * 100)
    print(profile(stem_s, stem_o, samples=10 ** 6))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    if '--md' in sys.argv:
        emit_md()
    else:
        show(sys.argv[1], sys.argv[2])
