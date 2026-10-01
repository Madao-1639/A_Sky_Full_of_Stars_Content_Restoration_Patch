"""Dump / diff YOZORA scene scripts: Steam side (asset _E) vs original side (Miazora).

Both sides carry the same English embedded fallback text, so their text records can
be compared directly. Chinese for the Steam side is looked up in asset/zh-CN/Rio.arc
by the record index (0x14 <idx u16> <flag u16> "char\\0" <text> "%K%P"; the engine
prefers .lng[idx] and falls back to the embedded text).

Reliable anchors only:
  0x14  text record                      -> 'text'
  0x34 <slot>\\0 <STEM>.PNA\\0            -> 'pna'   (CG in ev* slots, 立绘 in st* slots)
  0x04/0x07 <NAME>\\0                     -> 'goto'
  0x0b <u16> 0x01                         -> 'setvar'
  <NAME>.(PNG|OGG|WAV) outside text       -> 'res'   (背景 / 转场 / 遮罩 / 语音)

Note: 0x33 and 0x66 are NOT used as prefixes here -- they are the ASCII characters
'3' and 'f', which occur inside resource names (Dころな_03L.PNA, Effect03_...), so
scanning for them yields garbage.

Modes
-----
  counts <steam>:<mia> [...]   text-record counts per side (spot deletions at a glance)
  diff   <steam> <mia>         text diff; every line annotated with its 演出 context
  tail   <stem> [n]            last n raw events (default 25)
  head   <stem> [n]            first n raw events

<stem> = Rio.arc member name without extension, any case, `_E` included.
"""
import argparse
import difflib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tool import arcbuild, lng, ws2

ASSET_RIO = ROOT / 'asset' / 'Rio.arc'
ZH_RIO = ROOT / 'asset' / 'zh-CN' / 'Rio.arc'
MIA_RIO = ROOT.parent / 'MiazoraPatch(v1.2)' / '+18 Version' / 'Rio.arc'

TEXT = re.compile(rb'\x14(..)(..)char\x00(.*?)%K%P', re.S)
PNA = re.compile(rb'\x34([\x20-\x7e]{2,12})\x00([^\x00]{2,40}?)\.PNA\x00', re.I)
GOTO = re.compile(rb'[\x04\x07]([A-Z0-9_]{4,40})\x00')
SETV = re.compile(rb'\x0b(..)\x01')
RES = re.compile(rb'([A-Za-z0-9_\-]{4,40}\.(?:PNG|OGG|WAV))', re.I)

ARCHIVES = {}


def archive(side):
    if side not in ARCHIVES:
        path = {'asset': ASSET_RIO, 'zh': ZH_RIO, 'mia': MIA_RIO}[side]
        ARCHIVES[side] = {n.decode('utf-16le').upper(): d for n, d in arcbuild.read_raw(path)}
    return ARCHIVES[side]


def raw_of(stem):
    name = stem.upper() + '.WS2'
    blob = archive('asset').get(name)
    return blob if blob is not None else archive('mia').get(name)


def zh_of(stem):
    blob = archive('zh').get(stem.upper() + '.LNG')
    if blob is None:
        return []
    try:
        return lng.parse_lng(blob)
    except Exception:
        return []


def events(stem):
    """Ordered [(pos, kind, payload)]."""
    raw = raw_of(stem)
    if raw is None:
        raise SystemExit('script not found: %s' % stem)
    data = ws2.decode(raw)
    spans = [m.span() for m in TEXT.finditer(data)]

    def in_text(pos):
        return any(a <= pos < b for a, b in spans)

    evs = []
    for m in TEXT.finditer(data):
        evs.append((m.start(), 'text', (int.from_bytes(m.group(1), 'little'),
                                        int.from_bytes(m.group(2), 'little'),
                                        m.group(3).decode('shift_jis', 'replace'))))
    for pos, kind, rx, fn in (
            (0, 'pna', PNA, lambda m: (m.group(1).decode('ascii', 'replace'),
                                       m.group(2).decode('shift_jis', 'replace'))),
            (0, 'goto', GOTO, lambda m: m.group(1).decode('ascii', 'replace')),
            (0, 'setvar', SETV, lambda m: int.from_bytes(m.group(1), 'little')),
            (0, 'res', RES, lambda m: m.group(1).decode('shift_jis', 'replace'))):
        for m in rx.finditer(data):
            if in_text(m.start()):
                continue
            evs.append((m.start(), kind, fn(m)))
    evs.sort(key=lambda e: e[0])
    return evs


def annotate(stem):
    """[(idx, flag, en_text, zh, 演出描述)] -- 演出 = PNA slot state + resource names
    referenced since the previous text record."""
    evs = events(stem)
    zh = zh_of(stem)
    slots, gap, rows = {}, [], []
    for pos, kind, payload in evs:
        if kind == 'pna':
            slots[payload[0]] = payload[1]
        elif kind == 'res':
            if payload not in gap:
                gap.append(payload)
        elif kind == 'text':
            idx, flag, text = payload
            parts = ['%s=%s' % kv for kv in sorted(slots.items()) if kv[1]]
            if gap:
                parts.append('资源:' + ','.join(gap))
            rows.append((idx, flag, text, zh[idx] if 0 <= idx < len(zh) else None,
                         ' | '.join(parts)))
            gap = []
    return rows


def fmt(text, width=58):
    t = text.replace('\\n', '⏎')
    return t if len(t) <= width else t[:width] + '…'


def norm(text):
    """Line breaks are a literal 2-char '\\n' inside the record, and the two
    localisations wrap (and pad) at different points. Compare with whitespace
    collapsed, or a pure re-wrap is reported as a content change."""
    return re.sub(r'\s+', ' ', text.replace('\\n', '')).strip()


def cmd_counts(args):
    for pair in args.pairs:
        steam, mia = pair.split(':')
        s, m = annotate(steam), annotate(mia)
        print('%-32s steam=%-4d mia=%-4d diff=%+d' % (steam, len(s), len(m), len(s) - len(m)))


def cmd_diff(args):
    steam, mia = args.steam, args.mia
    s, m = annotate(steam), annotate(mia)
    print('=' * 104)
    print('steam = %s  (%d 句)' % (steam, len(s)))
    print('mia   = %s  (%d 句)' % (mia, len(m)))
    print('=' * 104)
    a = [norm(r[2]) for r in s]
    b = [norm(r[2]) for r in m]
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == 'equal':
            if i2 - i1 > args.quiet:
                print('\n      … %d 句相同 …\n' % (i2 - i1))
            else:
                for k in range(i1, i2):
                    print('  =   [%3d] %s' % (s[k][0], fmt(a[k])))
                    print('        zh: %s' % (s[k][3] or ''))
                    if s[k][4]:
                        print('        演出: %s' % s[k][4])
            continue
        if tag in ('replace', 'delete'):
            for k in range(i1, i2):
                print('  -   [%3d] %s' % (s[k][0], fmt(a[k])))
                print('        zh: %s' % (s[k][3] or ''))
                if s[k][4]:
                    print('        演出: %s' % s[k][4])
        if tag in ('replace', 'insert'):
            for k in range(j1, j2):
                print('  +   [%3d] %s' % (m[k][0], fmt(b[k])))
                if m[k][4]:
                    print('        演出: %s' % m[k][4])


def fmt_event(kind, payload):
    if kind == 'text':
        return 'text   idx=%-4d flag=%-3d %s' % (payload[0], payload[1], fmt(payload[2], 60))
    if kind == 'pna':
        return 'pna    slot=%-10s %s' % (payload[0], payload[1])
    if kind == 'goto':
        return 'goto   %s' % payload
    if kind == 'setvar':
        return 'setvar %d' % payload
    return '%-6s %s' % (kind, payload)


def cmd_window(args):
    evs = events(args.stem)
    picked = evs[-args.n:] if args.side == 'tail' else evs[:args.n]
    print('--- %s : %s %d of %d events ---' % (args.stem, args.side, len(picked), len(evs)))
    for pos, kind, payload in picked:
        print('  %7d  %s' % (pos, fmt_event(kind, payload)))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('counts')
    p.add_argument('pairs', nargs='+', help='steam_stem:mia_stem')
    p.set_defaults(func=cmd_counts)
    p = sub.add_parser('diff')
    p.add_argument('steam')
    p.add_argument('mia')
    p.add_argument('--quiet', type=int, default=6)
    p.set_defaults(func=cmd_diff)
    for side in ('tail', 'head'):
        p = sub.add_parser(side)
        p.add_argument('stem')
        p.add_argument('n', type=int, nargs='?', default=25)
        p.set_defaults(func=cmd_window, side=side)
    args = ap.parse_args()
    args.func(args)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
