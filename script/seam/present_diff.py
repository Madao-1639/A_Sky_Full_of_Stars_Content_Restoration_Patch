"""按**内容**对齐比对两个脚本的演出指令序列。

## 为什么不用 idx 对齐

Steam 增删/改写过多句，同一 `0x14` idx 在两侧**可能是不同内容**，按 idx 配对会刷出大量假差异。
本工具改成**按内容对齐**（与 `script/seam/seam_profile.py` 同一套逻辑）：

- **语音名序列**当锚点（语音名相同的句位视为同一句；本项目假定语音与文本语义一致）
- 语音名不同的位置 = **差异块**（Steam 重录过），块内**不做逐句配对**；
  仅当块内两侧句数相同时才按位置配对，并在报告里标注为「差异块内（按位置）」
- 锚点之间的**无语音句**按顺序配对（内容无法验证，标注为「无语音句」）

## 差异分类

1. `语音名不同` —— 预期差异：换回原版 OGG 即可
2. `资源名不同` —— `file` 类字段（`*.PNG/*.PNA/*.OGG/*.DAT`）变了
3. `演出参数不同` —— 透明度 / 帧号 / 坐标 / 秒数 / 特效参数等
4. `指令增删` —— 一侧有另一侧无

比较用**原始操作数字节**（不依赖解析字段，避免漏判），显示用可读字段。

用法:
  python script/seam/present_diff.py <steam_stem> <orig_stem>                 # 汇总 + 全部差异
  python script/seam/present_diff.py <steam_stem> <orig_stem> --only-diff     # 只列有差异的
  python script/seam/present_diff.py <steam_stem> <orig_stem> --idx 0,20-23   # 只看这些**原版** idx
  python script/seam/present_diff.py <steam_stem> <orig_stem> --md            # 输出 markdown 清单
"""
import argparse
import difflib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tool import arcbuild, ws2, ws2disasm

JP_RIO = ROOT.parent / '抬头看看吧看那天上的繁星' / 'Rio.arc'

VOICE_OP = 0x2e                  # CharMessageStart：本作的语音指令
TEXT_OP = 0x14                   # DisplayMessage
NAME_OP = 0x15                   # SetDisplayName（说话人前缀）
JUMP_OPS = {0x04, 0x07}          # RunFile / NextFile（不是演出）
# 引擎/系统指令：不是"演出"。Steam 的"跳过已读"机制（GetMsgSkip + Condition + Jump2）
# 就落在这一类；基底是 Steam 脚本 → 这类原样保留，不参与演出比对。
SYSTEM_OPS = {0x01, 0x02, 0x06, 0x18, 0x1c}
SKIP_OPS = JUMP_OPS | SYSTEM_OPS | {TEXT_OP, NAME_OP}

SHOW_KEYS = ('slot', 'chan', 'file', 'name', 'name2', 'frames', 'count', 'seconds',
             'id', 'value', 'vol', 'mode', 'w', 'a', 'b', 'x', 'y', 'u', 'v',
             'v1', 'v2', 'v3', 'v4', 'cfg', 'flag', 'flags')
HEX_KEYS = ('raw', 'f32hex', 'tail', 'head', 'u32')

_cache = {}


def blob(side, name):
    if side not in _cache:
        path = {'asset': ROOT / 'asset' / 'Rio.arc',
                'backup': ROOT / 'backup' / 'Rio.arc', 'jp': JP_RIO}[side]
        _cache[side] = {n.decode('utf-16le').upper(): d for n, d in arcbuild.read_raw(path)}
    return _cache[side].get(name.upper())


def slot_of(ins):
    """0x34 的槽名被解析器拆成 tag + slot（'st01' -> tag='s', slot='t01'），这里拼回。"""
    f = ins.fields
    slot = f.get('slot')
    tag = f.get('tag')
    if slot is not None and isinstance(tag, int) and 0x20 <= tag < 0x7f:
        return chr(tag) + str(slot)
    return slot


def show(ins):
    """一条指令的可读描述。"""
    f = ins.fields
    parts = [ws2disasm.opcode_name(ins.opcode)]
    if ins.opcode == 0x34:
        parts.append('slot=%s' % slot_of(ins))
    for key in SHOW_KEYS:
        if key not in f or f[key] in (None, ''):
            continue
        if key == 'slot' and ins.opcode == 0x34:
            continue                      # 已单独处理
        val = f[key]
        if ins.opcode == 0x34 and key == 'tag':
            continue
        parts.append('%s=%s' % (key, val))
    if len(parts) == 1:
        for key in HEX_KEYS:
            if key in f and f[key]:
                parts.append('%s=%s' % (key, f[key]))
                break
    if len(parts) == 1:
        parts.append(ins.operands.hex())
    return ' '.join(parts)


def resource_names(ins):
    """该指令携带的资源名（含扩展名的字段值）。"""
    out = []
    for key in ('file', 'name', 'name2'):
        val = ins.fields.get(key)
        if isinstance(val, str) and '.' in val:
            out.append(val)
    return out


def key_of(ins):
    """比较用的键。

    默认用**原始操作数字节**（不依赖解析字段，避免漏判）。唯一例外是 `0x11 SetTimer`：
    解析器实测本作有**两种编码并存**（`<name>\\0 [00] <f32>`，Steam 重写过的段落多一个
    `00` 分隔字节），语义相同而字节不同 —— 若按字节比会刷出一批"假差异"，
    故按语义字段（`name` + `seconds`）取键。
    """
    if ins.opcode == 0x11:
        f = ins.fields
        sec = f.get('seconds')
        return (ins.opcode, f.get('name'), None if sec is None else round(float(sec), 4))
    return (ins.opcode, ins.operands)


class Rec:
    __slots__ = ('idx', 'text', 'voice', 'seq', 'keys', 'ins', 'name')

    def __init__(self, idx, text, voice, seq, keys, ins, name):
        self.idx, self.text, self.voice = idx, text, voice
        self.seq, self.keys, self.ins, self.name = seq, keys, ins, name


def recs(side, stem):
    raw = blob(side, stem if stem.upper().endswith('.WS2') else stem.upper() + '.WS2')
    if raw is None:
        raise SystemExit('%s: %s 不存在' % (side, stem))
    ins = ws2disasm.disassemble(ws2.decode(raw))
    out, seq, keys, objs, voice = [], [], [], [], []
    for i in ins:
        if i.opcode == TEXT_OP:
            out.append(Rec(i.fields.get('id'), (i.fields.get('text') or ''), tuple(sorted(voice)),
                           list(seq), list(keys), list(objs), ''))
            seq, keys, objs, voice = [], [], [], []
        elif i.opcode in SKIP_OPS:
            continue
        elif i.opcode == VOICE_OP:
            if i.fields.get('file'):
                voice.append(i.fields['file'])
        else:
            seq.append(show(i))
            keys.append(key_of(i))
            objs.append(i)
    return out, ins


def parse_idx(spec):
    if not spec:
        return None
    keep = set()
    for part in spec.split(','):
        if '-' in part:
            a, b = part.split('-')
            keep.update(range(int(a), int(b) + 1))
        else:
            keep.add(int(part))
    return keep


def _label(k_neg, k_pos, ins_of):
    """一对 remove/add 的类别：资源名变了 → 资源名不同；否则就是参数被改。

    注意要**分别到各自那一侧**查指令对象：两个 key 本来就不同，用同一个 key 去两边查
    只会查到一侧，会把"资源名不同"误判成"参数不同"。
    """
    oi = ins_of[0].get(k_neg)
    si = ins_of[1].get(k_pos)
    if oi is not None and si is not None and resource_names(oi) != resource_names(si):
        return '资源名不同'
    return '演出参数不同'


def _groupname(desc):
    """同一条指令的"身份"：槽位/名字/通道/LayerConfig 的 id。用于把 remove/add 配对。"""
    import re as _re
    m = _re.search(r'\b(?:slot|name|chan|id)=(\S+)', desc)
    return m.group(1) if m else ''


def seq_diff(ko, ks, do, ds, io, is_):
    """对齐两条指令序列，返回 [(类别, 原版描述, Steam 描述), ...]。

    实现说明（前两版都踩过坑）：
    - 用 **idx** 当键 → Steam 增删过句子，同 idx 两侧内容不同 → 满屏假差异。
    - 用 **LCS 逐条对齐** → 同一记录内有多条**完全相同**的指令时（如重复出现的
      `DragBackground`/`LayerConfig`），LCS 会配出次优解，刷出成串"删+增"噪声。
    → 现在用**多重集差异**（对重复与位移都稳），再把**同 opcode 同槽位**的一对
      remove/add 配成"同一批指令被改写"（参数或资源名不同），剩下的才算增删。
    - 只在多重集完全相同时，才检查**顺序**是否不同（顺序也影响画面，单列一类）。
    """
    from collections import Counter, defaultdict

    ins_of = ({}, {})
    for k, i in zip(ko, io):
        ins_of[0].setdefault(k, i)
    for k, i in zip(ks, is_):
        ins_of[1].setdefault(k, i)
    desc_of = ({}, {})
    for k, d in zip(ko, do):
        desc_of[0].setdefault(k, d)
    for k, d in zip(ks, ds):
        desc_of[1].setdefault(k, d)

    co, cs = Counter(ko), Counter(ks)
    removes, adds = [], []
    for k in co:
        n = co[k] - cs.get(k, 0)
        if n > 0:
            removes.append([k, n, desc_of[0][k]])
    for k in cs:
        n = cs[k] - co.get(k, 0)
        if n > 0:
            adds.append([k, n, desc_of[1][k]])

    items = []
    if not removes and not adds:
        if ko != ks:
            items.append(('指令顺序不同', '（多重集相同，仅顺序不同）',
                          '顺序：%s' % ' → '.join(do[:6])))
        return items

    buckets = defaultdict(lambda: {'-': [], '+': []})
    for r in removes:
        buckets[(r[0][0], _groupname(r[2]))]['-'].append(r)
    for a in adds:
        buckets[(a[0][0], _groupname(a[2]))]['+'].append(a)

    for _key, sides in sorted(buckets.items(), key=lambda kv: repr(kv[0])):
        neg, pos = sides['-'], sides['+']
        n = min(len(neg), len(pos))
        for j in range(n):
            # 同槽位的一对：按类别配对（多数是"参数改了"或"资源名换了"）
            kind = _label(neg[j][0], pos[j][0], ins_of)
            items.append((kind, neg[j][2], pos[j][2]))
        for r in neg[n:]:
            items.append(('指令增删', '原版独有：%s%s' % (r[2], '（×%d）' % r[1] if r[1] > 1 else ''), ''))
        for a in pos[n:]:
            items.append(('指令增删', '', 'Steam 独有：%s%s' % (a[2], '（×%d）' % a[1] if a[1] > 1 else '')))
    return items


def block_delta(recs_o, recs_s):
    """未逐句配对的差异块：按**块级多重集**给出演出差异（不做逐句配对，避免假装精确）。"""
    from collections import Counter

    def agg(rs):
        c = Counter()
        for r in rs:
            c.update(r.keys)
        return c

    co, cs = agg(recs_o), agg(recs_s)
    dof, dsf = {}, {}
    for r in recs_o:
        for k, d in zip(r.keys, r.seq):
            dof.setdefault(k, d)
    for r in recs_s:
        for k, d in zip(r.keys, r.seq):
            dsf.setdefault(k, d)
    out = []
    for k in co:
        n = co[k] - cs.get(k, 0)
        if n > 0:
            out.append('原版独有：%s%s' % (dof[k], '（×%d）' % n if n > 1 else ''))
    for k in cs:
        n = cs[k] - co.get(k, 0)
        if n > 0:
            out.append('Steam 独有：%s%s' % (dsf[k], '（×%d）' % n if n > 1 else ''))
    return out


def run(steam, orig, only_diff=False, idx_filter=None, md=False):
    sr, s_all = recs('asset', steam)
    orr, o_all = recs('jp', orig)
    out = []
    P = out.append

    sm = difflib.SequenceMatcher(None, [r.voice for r in orr], [r.voice for r in sr], autojunk=False)
    ops = sm.get_opcodes()

    pairs, blocks = [], []
    for tag, i1, i2, j1, j2 in ops:
        if tag == 'equal':
            for k in range(i2 - i1):
                a, b = orr[i1 + k], sr[j1 + k]
                basis = '同语音锚点' if a.voice else '无语音句（按顺序配对）'
                pairs.append((a, b, basis))
        else:
            ko, ks = i2 - i1, j2 - j1
            label = {'replace': '语音名不同', 'delete': '原版有 / Steam 删',
                     'insert': 'Steam 新增'}[tag]
            block = {'label': label, 'o': (i1, i2), 's': (j1, j2)}
            if ko == ks and ko > 0:
                for k in range(ko):
                    pairs.append((orr[i1 + k], sr[j1 + k], '差异块内（按位置）'))
                block['paired'] = ko
            blocks.append(block)

    # ---- 逐对比较
    # 前 4 类是指令要求的分类；「指令顺序不同」是额外补充的一类（顺序也影响画面，
    # 若归入"指令增删"会误导，归入"相同"则会漏掉）
    kinds_order = ('语音名不同', '资源名不同', '演出参数不同', '指令增删', '指令顺序不同')
    findings = {k: [] for k in kinds_order}
    pair_rows = []
    for a, b, basis in pairs:
        row_kinds = set()
        if idx_filter is not None and (a.idx not in idx_filter):
            continue
        if a.voice != b.voice:
            findings['语音名不同'].append((a.idx, b.idx, basis,
                                       ','.join(a.voice) or '（无）', ','.join(b.voice) or '（无）'))
            row_kinds.add('语音名不同')
        for kind, x, y in seq_diff(a.keys, b.keys, a.seq, b.seq, a.ins, b.ins):
            findings[kind].append((a.idx, b.idx, basis, x, y))
            row_kinds.add(kind)
        pair_rows.append((a.idx, b.idx, basis, row_kinds))

    n_pairs = len(pairs)
    if md:
        P('# 演出差异清单：`%s` ⇄ 原版 `%s`' % (steam, orig))
        P('')
        P('对齐：原版 %d 句 / Steam %d 句；配对 %d 对（同语音锚点 %d / 无语音句 %d / 差异块内 %d）'
          % (len(orr), len(sr), n_pairs,
             sum(1 for *_, bs in pairs if bs == '同语音锚点'),
             sum(1 for *_, bs in pairs if bs.startswith('无语音句')),
             sum(1 for *_, bs in pairs if bs.startswith('差异块内'))))
        P('')
        P('| 类别 | 涉及句数（去重） | 差异处数 |')
        P('|---|---|---|')
        for kind in kinds_order:
            rows = findings[kind]
            P('| %s | %d | %d |' % (kind, len({r[0] for r in rows}), len(rows)))
        P('')
        for kind in kinds_order:
            rows = findings[kind]
            P('## %s（%d 处）' % (kind, len(rows)))
            P('')
            if not rows:
                P('（无）')
                P('')
                continue
            P('| 原版 idx | Steam idx | 位置 | 原版 | Steam |')
            P('|---|---|---|---|---|')
            for r in rows:
                P('| %s | %s | %s | %s | %s |' % (r[0], r[1], r[2], r[3], r[4]))
            P('')
        P('## 未逐句配对的差异块')
        P('')
        P('| 类型 | 原版 idx | 句数 | Steam idx | 句数 | 是否已按位置配对 |')
        P('|---|---|---|---|---|---|')
        for b in blocks:
            i1, i2 = b['o']
            j1, j2 = b['s']
            P('| %s | %s | %d | %s | %d | %s |'
              % (b['label'],
                 '%d–%d' % (orr[i1].idx, orr[i2 - 1].idx) if i2 > i1 else '—', i2 - i1,
                 '%d–%d' % (sr[j1].idx, sr[j2 - 1].idx) if j2 > j1 else '—', j2 - j1,
                 '是（%d 对）' % b['paired'] if b.get('paired') else '否'))
        P('')
        unpaired = [b for b in blocks if not b.get('paired')]
        if unpaired:
            P('### 未配对块的**块级**演出差异（不做逐句配对）')
            P('')
            for b in unpaired:
                i1, i2 = b['o']
                j1, j2 = b['s']
                P('**%s**：原版 idx %s（%d 句）⇄ Steam idx %s（%d 句）'
                  % (b['label'],
                     '%d–%d' % (orr[i1].idx, orr[i2 - 1].idx) if i2 > i1 else '—', i2 - i1,
                     '%d–%d' % (sr[j1].idx, sr[j2 - 1].idx) if j2 > j1 else '—', j2 - j1))
                P('')
                for line in block_delta(orr[i1:i2], sr[j1:j2]):
                    P('- %s' % line)
                P('')
        return '\n'.join(out)

    # ---- 文本输出
    print('=' * 100)
    print('%s（Steam %d 句 / %d 指令）  ⇄  %s（原版 %d 句 / %d 指令）'
          % (steam, len(sr), len(s_all), orig, len(orr), len(o_all)))
    print('配对 %d 对：同语音锚点 %d / 无语音句 %d / 差异块内 %d'
          % (n_pairs,
             sum(1 for *_, bs in pairs if bs == '同语音锚点'),
             sum(1 for *_, bs in pairs if bs.startswith('无语音句')),
             sum(1 for *_, bs in pairs if bs.startswith('差异块内'))))
    print('=' * 100)
    for kind in kinds_order:
        rows = findings[kind]
        print('%-14s 涉及 %3d 句 / %3d 处' % (kind, len({r[0] for r in rows}), len(rows)))
    print()
    if not only_diff:
        print('--- 逐对一览（原版 idx ⇄ Steam idx）')
        for idx_o, idx_s, basis, kk in pair_rows:
            print('  原版[%3d] ⇄ Steam[%3d]  %-22s %s'
                  % (idx_o, idx_s, basis, '差异：' + '/'.join(sorted(kk)) if kk else '相同'))
        print()
    for kind in kinds_order:
        rows = findings[kind]
        if not rows:
            continue
        print('--- %s' % kind)
        for r in rows:
            print('  原版[%s] ⇄ Steam[%s]  [%s]' % (r[0], r[1], r[2]))
            print('      原版  %s' % r[3])
            print('      Steam %s' % r[4])
    if blocks:
        print('\n--- 未逐句配对的差异块')
        for b in blocks:
            i1, i2 = b['o']
            j1, j2 = b['s']
            print('  %-16s 原版 idx %s（%d 句） ⇄ Steam idx %s（%d 句）%s'
                  % (b['label'],
                     '%d–%d' % (orr[i1].idx, orr[i2 - 1].idx) if i2 > i1 else '—', i2 - i1,
                     '%d–%d' % (sr[j1].idx, sr[j2 - 1].idx) if j2 > j1 else '—', j2 - j1,
                     '  ※已按位置配对' if b.get('paired') else ''))
            if not b.get('paired'):
                for line in block_delta(orr[i1:i2], sr[j1:j2]):
                    print('        %s' % line)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('steam')
    ap.add_argument('orig')
    ap.add_argument('--only-diff', action='store_true')
    ap.add_argument('--idx', default='')
    ap.add_argument('--md', action='store_true')
    a = ap.parse_args()
    md = run(a.steam, a.orig, a.only_diff, parse_idx(a.idx), a.md)
    if md:
        print(md)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
