"""按施工单重建一个**差分接缝**脚本（Steam `*_E` 基底 + 演出整套回原版）。

是试点构建器（硬编码 103e）的通用化版；`--pilot-compat` 必须对 103e **逐字节复现**。

用法:
  python script/seam/build_seam.py --steam yozora_hika_103c_E --orig yozora_hika_103c \
      --translations tmp/seams/yozora_hika_103c.translations.json \
      --rename-json tmp/seams/yozora_hika_103c.rename.json \
      [--nametable-json tmp/seams/_nametable.json] \
      [--dry] [--dump] [--emit-body PATH] [--check-lng]
  # 归档路径可用 --asset-rio/--jp-rio/--zh-rio 覆盖（默认项目内真实归档；测试时可指向副本）

规则（继承试点，另见 doc/file-formats.md 的「差分接缝修复」）：
  - 基底 = Steam `_E` 脚本原始字节（rot6）
  - 记录配对用**语音签名**；`o2s` 里配上的 = "共用句"，未配上 / 落入 `restore` 集合的 =
    "差分类"，**整条取原版**（文本 + 前缀 + 语音 + 演出）
  - 共用句：文本/前缀用 Steam，演出指令按 `resource/present-ops.json` 的策略合并
  - **`restore` = 未配对记录 ∪ `resource/seam-diffs.json` 的 semantic 区间**
    （同句数无语音句的语义改写：语音、句数都看不出，必须显式列出）
    `text` 条目的区间是**块级**的——块内被 1:1 语音配对上的记录按项目前提"同语音即同句"
    保留 Steam（构建时会逐条列出供人核）；`--strict-text-diff` 改为把 `text` 区间也整体
    纳入 `restore`（会与试点的逐字节回归冲突，仅供对照测量）
  - `0x11 SetTimer`：两侧秒数相同时落成 equal → 取 Steam 编码形态（用户裁定"编码形态用
    Steam、秒数取值用原版"）
  - 文本 id 重排 `0..N-1`；资源改名按 `--rename-json`；`0x01`/`0x02`/`0x06` 绝对偏移重定位
  - `.lng` 条数 = 原版句数；共用句取 Steam `.lng` 对应条，差分类用 `--translations`
"""
import argparse
import difflib
import hashlib
import json
import shutil
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tool import arcbuild, lng, ws2, ws2disasm, ws2patch              # noqa: E402

JP_RIO = ws2patch.JP_RIO
ASSET_RIO = ws2patch.ASSET_RIO
ZH_RIO = ws2patch.ZH_RIO
SD_JSON = ROOT / 'resource' / 'seam-diffs.json'

TEXT, NAME, VOICE, STOP = 0x14, 0x15, 0x2e, 0x1f
TIMER, JUMP, JUMP2, COND = 0x11, 0x06, 0x02, 0x01
ENDREC = 0xff

# ---- 指令策略（resource/present-ops.json）----------------------------------
POLICY, _OPS_BY_NAME, _OPS_RAW = ws2patch.load_present_ops()
KEEP_STEAM = {op for op, pol in POLICY.items() if pol == 'keep_steam'}
# 例外 1：`0xff` 虽标 keep_steam，但两侧操作数不同（原版 d5… / Steam 95…），应"只按 opcode
# 配对"从而落成 equal 取 Steam 字节。
# 例外 2：`0x04 RunFile` 是**调用**（LAYER_ORDER / CG_ACHIEVEMENT 注入），两侧的顺序与调用
# 都要保：按 (opcode, 操作数) 正常配对（同键 → 取 Steam 字节，位置不动），两侧都有但不同则
# 两条都发（一侧的成就注入、另一侧的 LAYER_ORDER 都不丢）。
KEEP_PAIR = {ENDREC}
PAIRABLE_KEEP = {0x04}
NOPAIR = KEEP_STEAM - KEEP_PAIR - PAIRABLE_KEEP
# `--pilot-compat`：复刻试点构建器的合并语义，用于 103e 的逐字节回归。
SENT_COMPAT = {0x01, 0x02, 0x06, 0x1c}       # build_103e 里"只保留 Steam 侧"的机制类
SEMI_COMPAT = {TIMER}
WARNED = set()


def policy(op):
    pol = POLICY.get(op)
    if pol is None:
        if op not in WARNED:
            WARNED.add(op)
            print('!! 未分类 opcode %s，按 keep_steam 处理' % hex(op), file=sys.stderr)
        return 'keep_steam'
    return pol


# ---- 归档/脚本读写 ---------------------------------------------------------
def load(path):
    return {n.decode('utf-16le'): (n, d) for n, d in arcbuild.read_raw(path)}


def find(members, stem):
    for name, (nb, data) in members.items():
        if name.upper() == (stem + '.WS2').upper():
            return name, data
    raise SystemExit('%s 不存在' % stem)


def find_member(members, name):
    for nm, (nb, data) in members.items():
        if nm.upper() == name.upper():
            return nb, data
    raise SystemExit('%s 不存在' % name)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def segment(ins):
    """切 pre / records / tail；每条记录以 `0x14` 收尾。"""
    pre, recs, cur = [], [], []
    for i in ins:
        cur.append(i)
        if i.opcode == TEXT:
            recs.append(cur)
            cur = []
    return pre, recs, cur


def voice_sig(rec):
    return tuple(sorted(i.fields.get('file') or '' for i in rec if i.opcode == VOICE))


# ---- seam-diffs.json -------------------------------------------------------
def seam_entry(stem_s):
    sd = json.loads(SD_JSON.read_text(encoding='utf-8'))
    for s in sd['scripts']:
        if s['steam'].upper() == stem_s.upper():
            return s
    raise SystemExit('resource/seam-diffs.json 里没有 %s' % stem_s)


def _ranges(items, key, n_o):
    out = set()
    for it in items:
        r = it.get(key)
        if r:
            lo, hi = min(r), max(r)
            out.update(i for i in range(lo, hi + 1) if 0 <= i < n_o)
    return out


# ---- 合并 ------------------------------------------------------------------
def mkey(ins, side, compat=False):
    if ins.opcode == TIMER:
        return (ins.opcode, ins.fields.get('seconds'))
    if ins.opcode in KEEP_PAIR:
        return (ins.opcode,)                     # 只按键配对 → 落成 equal，取 Steam 字节
    if compat:
        if ins.opcode in SENT_COMPAT:
            return (ins.opcode, ins.operands, side)
        return (ins.opcode, ins.operands)
    if ins.opcode in NOPAIR:
        return (ins.opcode, side)                # 永不与对侧配对
    return (ins.opcode, ins.operands)


_jump_targets = ws2patch.jump_targets


def _block_keep(S_seq, j1, j2, keep_emit, added):
    """block [j1,j2) 内应发出的 Steam 下标。

    基础 = `keep_emit` 类。**再由跳转闭包补上被它们引用、却落在同一 block 内的指令**
    （典型：Steam 新增的跳过已读机制 `[0x1c][0x01][0x1f][0x02][0x1f]` —— `0x01` 的
    a/b 指向那两条 `0x1f StopMusic`；`0x1f` 是 `use_orig`，原先被 merge 丢掉，导致机制组
    的跳转目标在新脚本里不存在、绝对偏移无法重定位）。只在**同一 block 内**补，保证
    Steam 侧相对顺序不变。
    """
    keep = {k for k in range(j1, j2) if S_seq[k].opcode in keep_emit}
    if not keep:
        return keep
    by_off = {S_seq[k].offset: k for k in range(j1, j2)}
    frontier = set(keep)
    while frontier:
        new = set()
        for k in frontier:
            for t in _jump_targets(S_seq[k]):
                if not t:                          # 0 = "不跳转"哨兵；None = 未解析
                    continue
                kk = by_off.get(t)
                if kk is not None and kk not in keep:
                    keep.add(kk)
                    new.add(kk)
                    added.add((S_seq[kk].offset, ws2disasm.opcode_name(S_seq[kk].opcode)))
        frontier = new
    return keep


def merge(O_seq, S_seq, compat=False, added=None):
    """对齐两侧指令序列，每个 block 只取一侧。

    - `equal`   ：两侧同键（opcode + 操作数）→ 取 Steam 侧字节
    - `replace` ：取原版；Steam 侧只保留 keep_steam 类
    - `delete`  ：原版独有 → 取原版（faithful：keep_steam 类若对侧块内有同 opcode 则弃用）
    - `insert`  ：Steam 独有 → 只保留 keep_steam 类，其余丢弃（Steam 新增的纯演出）

    faithful 模式另用 `_block_keep`：keep_steam 的机制类若其跳转目标在同一 block 内，
    目标一并保留（见 `_block_keep` 的说明）；`--pilot-compat` 保持老行为。
    """
    om = difflib.SequenceMatcher(None, [mkey(i, 'o', compat) for i in O_seq],
                                 [mkey(i, 's', compat) for i in S_seq], autojunk=False)
    keep_emit = SENT_COMPAT if compat else KEEP_STEAM
    out = []
    for tag, i1, i2, j1, j2 in om.get_opcodes():
        if tag == 'equal':
            for k in range(j1, j2):
                out.append(('s', k))
            continue
        jops = {S_seq[k].opcode for k in range(j1, j2)}
        for k in range(i1, i2):                  # replace / delete：原版
            if not compat and O_seq[k].opcode in NOPAIR and O_seq[k].opcode in jops:
                continue                         # 两侧都有 → 用 Steam 版（Steam 胜出）
            out.append(('o', k))
        if compat or added is None:
            sk = {k for k in range(j1, j2) if S_seq[k].opcode in keep_emit}
        else:
            sk = _block_keep(S_seq, j1, j2, keep_emit, added)
        for k in range(j1, j2):                  # replace / insert：keep_steam 类也发
            if k in sk:
                out.append(('s', k))
    return out


# ---- 计划 ------------------------------------------------------------------
def build_plan(asset, jp, sc, strict_text=False, whole_blocks=(), compat=False, added=None):
    # added=None → 不启用机制跳转闭包（第一遍）；传一个 set 则启用并把补入的指令记进去
    stem_s, stem_o = sc['steam'], sc['orig']
    _, s_raw = find(asset, stem_s)
    _, o_raw = find(jp, stem_o)
    s_dec, o_dec = ws2.decode(s_raw), ws2.decode(o_raw)
    S, O = ws2disasm.disassemble(s_dec), ws2disasm.disassemble(o_dec)
    SB = {i.offset: s_dec[i.offset:i.offset + i.size] for i in S}
    OB = {i.offset: o_dec[i.offset:i.offset + i.size] for i in O}
    pre_o, recs_o, tail_o = segment(O)
    pre_s, recs_s, tail_s = segment(S)
    n_o, n_s = len(recs_o), len(recs_s)

    om = difflib.SequenceMatcher(None, [voice_sig(r) for r in recs_o],
                                 [voice_sig(r) for r in recs_s], autojunk=False)
    o2s, used_s = {}, set()
    for tag, i1, i2, j1, j2 in om.get_opcodes():
        if tag == 'equal':
            for k in range(i2 - i1):
                o2s[i1 + k] = j1 + k
                used_s.add(j1 + k)

    unpaired = {i for i in range(n_o) if i not in o2s}
    sem = _ranges(sc.get('semantic', []), 'orig_idx', n_o)
    txt = _ranges(sc.get('text', []), 'orig_range', n_o)
    wb = set()
    for lo, hi in whole_blocks:
        wb.update(i for i in range(lo, hi + 1) if 0 <= i < n_o)
    restore = set(unpaired) | sem | wb
    if strict_text:
        restore |= txt
    for oi in restore:                            # 差分类 → 整条取原版
        used_s.discard(o2s.pop(oi, None))
    used_s = {j for j in used_s if 0 <= j < n_s}

    # `text` 块逐项审计：块内"还原几条 / 保留 Steam 几条"。**同时含两者的块**是
    # "整块取原版"的候选（如 103e 的尾部块 76–86），需人工确认后写进 --whole-blocks。
    blocks = []
    for t in sc.get('text', []):
        r = t.get('orig_range')
        if not r:
            continue
        lo, hi = min(r), max(r)
        recs = [i for i in range(lo, hi + 1) if 0 <= i < n_o]
        blocks.append({'kind': t['kind'], 'orig_range': [lo, hi], 'steam_range': t['steam_range'],
                       'n': [t['orig_n'], t['steam_n']],
                       'restored': [i for i in recs if i in restore],
                       'kept': [i for i in recs if i not in restore],
                       'mixed': bool([i for i in recs if i in restore]
                                     and [i for i in recs if i not in restore])})
    audit = {
        'text_records': sorted(txt), 'semantic_records': sorted(sem), 'whole_blocks': sorted(wb),
        'unpaired': sorted(unpaired), 'restore': sorted(restore), 'blocks': blocks,
        'kept_steam_in_textblocks': sorted(txt - restore),
        'text_only_not_restored': sorted(txt - restore),
    }
    bad_o = [oi for oi, r in enumerate(recs_o) if r[-1].fields.get('id') != oi]
    bad_s = [j for j, r in enumerate(recs_s) if r[-1].fields.get('id') != j]
    meta = dict(o2s=o2s, used_s=used_s, n_o=n_o, n_s=n_s, recs_o=recs_o, recs_s=recs_s,
                restore=restore, audit=audit, id_misalign=(bad_o, bad_s))

    plan = []
    for src, k in merge(pre_o, pre_s, compat, added):
        plan.append(('o', pre_o[k]) if src == 'o' else ('s', pre_s[k]))
    for oi, o_rec in enumerate(recs_o):
        si = o2s.get(oi)
        if si is None:
            plan += [('o', i) for i in o_rec]         # 差分类：整条取原版
        else:
            s_rec = recs_s[si]
            perf_o = [i for i in o_rec if i.opcode not in (TEXT, NAME)]
            perf_s = [i for i in s_rec if i.opcode not in (TEXT, NAME)]
            for src, k in merge(perf_o, perf_s, compat, added):
                plan.append(('o', perf_o[k]) if src == 'o' else ('s', perf_s[k]))
            plan += [('s', i) for i in s_rec if i.opcode in (NAME, TEXT)]   # 共用句文本/前缀用 Steam
    for src, k in merge(tail_o, tail_s, compat, added):
        plan.append(('o', tail_o[k]) if src == 'o' else ('s', tail_s[k]))
    return plan, meta, (SB, OB), (S, O)


def place_mechanisms(plan):
    """把「跳过已读」机制三条 `[0x1c][0x01][0x02]` 移到它们守卫的 `0x1f StopMusic` 之前。

    目标形态：`GetMsgSkip → Condition → Jump2 → StopMusic → 过渡簇`，使 `Condition.a` =
    Jump2 之后那条 StopMusic、`Condition.b` = Jump2 目标 = 过渡簇起点，与 Steam 同构。

    机制与 StopMusic 之间允许夹少量"透明"指令（如 `0x15 SetDisplayName ''`，Steam 独有、
    与演出无关但按策略保留）——整段一起前移，夹带指令留在 StopMusic 之前。
    """
    triple = [0x1c, 0x01, 0x02]
    transparent = {0x15}
    runs, k = [], 0
    while k + 3 <= len(plan):
        if [plan[k + j][1].opcode for j in range(3)] == triple:
            j = k - 1
            while j >= 0 and plan[j][1].opcode in transparent:
                j -= 1
            if j >= 0 and plan[j][1].opcode == STOP:
                runs.append((j, k))              # (StopMusic 位置, 机制组起点)
            k += 3
        else:
            k += 1
    for stop, tstart in reversed(runs):
        blk = plan[stop + 1:tstart + 3]
        del plan[stop + 1:tstart + 3]
        plan[stop:stop] = blk

    sites, no_cluster, k = [], [], 0
    while k + 3 <= len(plan):
        if [plan[k + j][1].opcode for j in range(3)] == triple:
            ok = (k + 6 < len(plan) and plan[k + 3][1].opcode == STOP
                  and plan[k + 4][1].opcode == 0x16 and plan[k + 5][1].opcode == 0x64
                  and plan[k + 6][1].opcode == 0x37)
            (sites if ok else no_cluster).append(k)
            k += 3
        else:
            k += 1
    mech = [x for x in plan if x[1].opcode in triple]
    orphan = len(mech) - 3 * (len(sites) + len(no_cluster))
    return sites, no_cluster, orphan


# ---- 资源改名 --------------------------------------------------------------
def _ascii_variants(b):
    """Shift-JIS 字节串的 ASCII 大小写变体（只翻转 ASCII 字母，不动高位字节）。"""
    return {b, bytes(c | 0x20 if 0x41 <= c <= 0x5A else c for c in b),
            bytes(c & ~0x20 if 0x61 <= c <= 0x7A else c for c in b)}


def load_renames(path):
    if not path:
        return []
    d = json.loads(Path(path).read_text(encoding='utf-8'))
    return [(k, v) for k, v in d.items() if v and not k.startswith('_')]


def apply_renames(raw, renames, counter):
    for old, new in renames:
        try:
            variants = _ascii_variants(old.encode('shift_jis'))
        except UnicodeEncodeError:
            continue
        nb = new.encode('shift_jis')
        for o in variants:
            if o and o != nb and o in raw:
                counter[(old, new)] = counter.get((old, new), 0) + raw.count(o)
                raw = raw.replace(o, nb)
    return raw


# ---- NameTable -------------------------------------------------------------
def load_nametable(path):
    if not path or not Path(path).exists():
        return {}
    return {k: v for k, v in json.loads(Path(path).read_text(encoding='utf-8')).items()
            if not k.startswith('_')}


# ---- 构建 ------------------------------------------------------------------
def build(asset, jp, sc, translations, renames, strict_text=False, whole_blocks=(),
          compat=False, verbose=True):
    """返回 dict(...)，不写盘。"""
    # 第一遍按老规则装配；**只有当重定位失败**（机制组的跳转目标被 merge 丢掉、连回退
    # 映射都解析不到）时，才重装第二遍并启用"机制跳转闭包"（把目标一并从 Steam 取回）。
    # 这样其余场景的产物逐字节不变；`--pilot-compat` 只装一遍。
    attempts = 1 if compat else 2
    added = None
    for attempt in range(attempts):
        added = None if attempt == 0 else set()
        plan, meta, (SB, OB), (S, O) = build_plan(asset, jp, sc, strict_text, whole_blocks,
                                                 compat, added)
        o2s, recs_o = meta['o2s'], meta['recs_o']
        sites, no_cluster, orphan = place_mechanisms(plan)

        rcount, norm = {}, []
        for src, ins in plan:
            raw = (OB if src == 'o' else SB)[ins.offset]
            if renames:
                raw = apply_renames(raw, renames, rcount)
            norm.append([src, ins, raw])

        ordv = 0
        for e in norm:
            if e[1].opcode == TEXT:
                ops = bytearray(e[1].operands)
                struct.pack_into('<H', ops, 0, ordv)
                e[2] = bytes([TEXT]) + bytes(ops)
                e[1].fields['id'] = ordv
                ordv += 1

        out, offs, side_map = bytearray(), [], {'o': {}, 's': {}}
        for src, ins, raw in norm:
            offs.append(len(out))
            side_map[src].setdefault(ins.offset, len(out))
            out += raw

        reloc, fail, inert = [], [], []
        for k, (src, ins, raw) in enumerate(norm):
            if ins.opcode in (JUMP2, COND):
                ops = bytearray(ins.operands)
                if ins.opcode == JUMP2:              # Jump2.a = 紧后 StopMusic 的再下一条
                    a_old = int.from_bytes(ops[0:4], 'little')
                    if k + 2 < len(norm) and norm[k + 1][1].opcode == STOP:
                        tgt = offs[k + 2]
                    elif a_old == 0:
                        inert.append(('0x02', ins.offset, 0, offs[k]))
                        continue                     # "不跳转"哨兵 → 字节原样
                    else:
                        tgt = side_map[src].get(a_old)
                        if tgt is None:
                            fail.append(('0x02', ins.offset, 'jump2', ins.fields.get('a')))
                            continue
                    struct.pack_into('<I', ops, 0, tgt)
                    reloc.append(('0x02', ins.offset, ins.fields.get('a'), tgt))
                else:                                # Condition.a = StopMusic；.b = 簇起点
                    a_old = int.from_bytes(ops[7:11], 'little')
                    b_old = int.from_bytes(ops[11:15], 'little')
                    if (k + 3 < len(norm) and norm[k + 1][1].opcode == JUMP2
                            and norm[k + 2][1].opcode == STOP):
                        fa, fb = offs[k + 2], offs[k + 3]
                    else:
                        fa = 0 if a_old == 0 else side_map[src].get(a_old)
                        fb = 0 if b_old == 0 else side_map[src].get(b_old)
                        if fa is None or fb is None:
                            if a_old == 0 or b_old == 0:
                                # 一侧是"不跳转"哨兵、另一侧越界 → 多半不是真的条件跳转
                                # （如 0x35 PlayMovie 的内联参数被解析成 0x01）→ 字节原样
                                inert.append(('0x01', ins.offset, (a_old, b_old), offs[k]))
                                continue
                            fail.append(('0x01', ins.offset, 'cond',
                                         (ins.fields.get('a'), ins.fields.get('b'))))
                            continue
                    struct.pack_into('<I', ops, 7, fa)
                    struct.pack_into('<I', ops, 11, fb)
                    reloc.append(('0x01', ins.offset, (ins.fields.get('a'), ins.fields.get('b')),
                                  (fa, fb)))
                norm[k][2] = bytes([ins.opcode]) + bytes(ops)
            elif ins.opcode == JUMP:                 # Jump.a = 文件内绝对偏移
                ops = bytearray(ins.operands)
                a_old = int.from_bytes(ops[0:4], 'little')
                if a_old == 0:
                    inert.append(('0x06', ins.offset, 0, offs[k]))
                    continue
                tgt = side_map[src].get(a_old)
                if tgt is None:
                    fail.append(('0x06', ins.offset, 'jump', ins.fields.get('a')))
                    continue
                struct.pack_into('<I', ops, 0, tgt)
                reloc.append(('0x06', ins.offset, ins.fields.get('a'), tgt))
                norm[k][2] = bytes([ins.opcode]) + bytes(ops)

        if not fail or attempt == attempts - 1:
            break
    added = added or set()

    body = b''.join(raw for _, _, raw in norm)
    missing = [i for i in sorted(meta['restore']) if i not in translations]

    # 绝对偏移硬自检：每条 0x01/0x02/0x06 的目标都必须落在**指令边界**上
    # （目标 0 = "不跳转"哨兵，跳过；被判为 inert 的疑似非指令也跳过）
    inert_off = {t[3] for t in inert}
    ins_body = ws2disasm.disassemble(body)
    for op, off, t in ws2patch.check_boundaries(ins_body, skip_offsets=inert_off):
        fail.append((hex(op), off, 'target-not-boundary', t))

    d = dict(body=body, meta=meta, norm=norm, reloc=reloc, fail=fail, missing=missing,
             sites=sites, no_cluster=no_cluster, orphan=orphan, renames=rcount,
             inert=inert, mech_added=sorted(added), n_instr=len(norm), n_shared=sum(
                 1 for oi in range(meta['n_o']) if oi in o2s))
    if verbose:
        a = meta['audit']
        print('原版 %d 记录 / Steam %d 记录；共用 %d；差分类 %d（= 未配对 %d ∪ 语义 %d%s）'
              % (meta['n_o'], meta['n_s'], len(o2s), len(meta['restore']),
                 len(a['unpaired']), len(a['semantic_records']),
                 ' ∪ 文本块 %d' % len(a['text_records']) if strict_text else ''))
        print('机制组重排 %d 处；游离机制指令 %d 条' % (len(sites) + len(no_cluster), orphan))
        if added:
            print('  机制跳转闭包补入 Steam 指令 %d 条（原为 use_orig、会被丢弃）：%s'
                  % (len(added), sorted(added)))
        if inert:
            print('  疑似非指令（目标含哨兵 0 且另一侧越界）保持字节原样 %d 处：%s'
                  % (len(inert), [(t[0], t[1], t[2]) for t in inert]))
        if rcount:
            print('资源改名 %d 处：%s' % (sum(rcount.values()),
                                          {'%s→%s' % k: v for k, v in rcount.items()}))
        print('重建后 %d 字节；指令 %d' % (len(body), len(norm)))
        for kind, off, old, new in reloc:
            print('  重定位 %s @%-6d %s -> %s' % (kind, off, old, new))
        if fail:
            print('!! 无法重定位 → 停手：%s' % fail)
        if a['kept_steam_in_textblocks']:
            print('\n校验：`text` 块内被 1:1 语音配对、保留 Steam 的记录 %d 条（%s）'
                  '—— 按"同语音即同句"前提保留 Steam 文本' % (
                      len(a['kept_steam_in_textblocks']), a['kept_steam_in_textblocks']))
        mixed = [b for b in a['blocks'] if b['mixed']]
        if mixed:
            print('\n校验：**同时含"还原"与"保留 Steam"** 的 text 块 %d 个'
                  '（"整块取原版"的候选，需人核后写进 --whole-blocks）：' % len(mixed))
            for b in mixed:
                print('   %-12s orig=%s steam=%s n=%s  还原 %s / 保留 %s'
                      % (b['kind'], b['orig_range'], b['steam_range'], b['n'],
                         b['restored'], b['kept']))
        if a['whole_blocks']:
            print('\n--whole-blocks 指定整块取原版的记录 %d 条：%s'
                  % (len(a['whole_blocks']), a['whole_blocks']))
    return d


def make_lng(meta, translations, steam_lng):
    o2s, n = meta['o2s'], meta['n_o']
    out = []
    for oi in range(n):
        si = o2s.get(oi)
        out.append(steam_lng[si] if si is not None else translations[oi])
    return out


def needed_prefixes(body):
    return sorted({i.fields.get('prefix') or '' for i in ws2disasm.disassemble(body)
                   if i.opcode == NAME and (i.fields.get('prefix') or '')})


# ---- 写入 ------------------------------------------------------------------
def write_out(d, sc, new_stem, args, asset_rio, zh_rio, translations, nametable):
    body, meta = d['body'], d['meta']
    for p in (asset_rio, zh_rio):
        b = p.with_name(p.name + '.before_seam_%s' % new_stem)
        if not b.exists():
            shutil.copy2(p, b)
            assert sha(b.read_bytes()) == sha(p.read_bytes()), '备份校验失败'
    print('备份完成：%s / %s' % (asset_rio.name + '.before_seam_' + new_stem,
                                 zh_rio.name + '.before_seam_' + new_stem))

    callers = []
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        import gen_worklist as GW
        callers = GW.callers_of(args.steam)
    except Exception as e:                                            # noqa: BLE001
        print('（未能自动求引用者：%s）' % e)
    caller_set = {c.upper() + '.WS2' for c in callers}
    new_member = (new_stem.lower() + '.ws2').encode('utf-16le')

    mem_s = arcbuild.read_raw(asset_rio)
    out_members, patched = [], {}
    for nb, dd in mem_s:
        nm = nb.decode('utf-16le')
        if nm.upper() == new_member.decode('utf-16le').upper():
            continue                                    # 幂等：先移除同名新脚本
        if nm.upper() in caller_set:
            dec = ws2.decode(dd)
            n = 0
            for op in (0x04, 0x07):
                oldb = bytes([op]) + args.steam.upper().encode('ascii') + b'\x00'
                newb = bytes([op]) + new_stem.upper().encode('ascii') + b'\x00'
                if oldb in dec:
                    n += dec.count(oldb)
                    dec = dec.replace(oldb, newb)
            if n:
                dd = ws2.encode(dec)
                patched[nm] = n
            if b'EVRET' in dec:
                print('  ! %s 含 EVRET → 改完必须重跑 script/tools/fix_evret_offsets.py' % nm)
        out_members.append((nb, dd))
    new_bytes = ws2.encode(body)
    out_members.append((new_member, new_bytes))
    arcbuild.write_arc(out_members, asset_rio)
    arcbuild.verify(asset_rio, expect_count=len(out_members))
    print('%s：%d -> %d 成员；跳转改写 %s' % (asset_rio.name, len(mem_s), len(out_members),
                                              patched or '无'))
    back = {nb.decode('utf-16le'): dd for nb, dd in arcbuild.read_raw(asset_rio)}
    assert back[new_member.decode('utf-16le')] == new_bytes, '新脚本回读不一致'

    zh = arcbuild.read_raw(zh_rio)
    zh_dict = {nb.decode('utf-16le'): (nb, dd) for nb, dd in zh}
    _, s_lng_raw = find_member({k: (k, v[1]) for k, v in zh_dict.items()},
                               sc['steam'] + '.lng')
    s_lng = lng.parse_lng(s_lng_raw)
    new_lng = make_lng(meta, translations, s_lng)
    assert len(new_lng) == meta['n_o'], len(new_lng)
    assert lng.parse_lng(lng.encode_lng(new_lng)) == new_lng, '.lng 编解码不自洽'
    zh_dict[new_stem.lower() + '.lng'] = ((new_stem.lower() + '.lng').encode('utf-16le'),
                                          lng.encode_lng(new_lng))

    nt = zh_dict['NameTable.txt'][1].decode('utf-16le')
    keys = {ln.split('\t')[0] for ln in nt.split('\r\n') if '\t' in ln}
    need = needed_prefixes(body)
    missing_nt = [p for p in need if p not in keys and p not in nametable]
    if missing_nt:
        raise SystemExit('NameTable 缺映射且未提供 --nametable-json：%s' % missing_nt)
    added = []
    for src, dst in nametable.items():
        if src in need and src not in keys:
            nt = nt.rstrip('\r\n') + '\r\n' + '%s\t%s' % (src, dst) + '\r\n'
            added.append('%s→%s' % (src, dst))
    zh_dict['NameTable.txt'] = ('NameTable.txt'.encode('utf-16le'), nt.encode('utf-16le'))
    arcbuild.write_arc(list(zh_dict.values()), zh_rio)
    arcbuild.verify(zh_rio)
    backz = {nb.decode('utf-16le'): dd for nb, dd in arcbuild.read_raw(zh_rio)}
    assert lng.parse_lng(backz[new_stem.lower() + '.lng']) == new_lng, '.lng 回读不一致'
    print('zh-CN/Rio.arc：%d -> %d 成员；%s.lng %d 条（共用 %d + 新译 %d）；NameTable 新增 %s'
          % (len(zh), len(zh_dict), new_stem.lower(), len(new_lng),
             meta['n_o'] - len(meta['restore']), len(meta['restore']), added or '无'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--steam', required=True)
    ap.add_argument('--orig', required=True)
    ap.add_argument('--translations', required=True)
    ap.add_argument('--rename-json')
    ap.add_argument('--nametable-json')
    ap.add_argument('--whole-blocks', metavar='PATH',
                    help='JSON [[lo,hi],...]：这些原版记录区间**整块取原版**（施工单里'
                         '"尾部块/整块按原版重建"的人工决定；不指定则不整块还原）')
    ap.add_argument('--asset-rio', default=str(ASSET_RIO))
    ap.add_argument('--jp-rio', default=str(JP_RIO))
    ap.add_argument('--zh-rio', default=str(ZH_RIO))
    ap.add_argument('--strict-text-diff', action='store_true')
    ap.add_argument('--pilot-compat', action='store_true',
                    help='复刻试点构建器的合并语义（0x04/0x07/0x0b/0x15 等按老行为处理），'
                         '用于 103e 的逐字节回归；一般批量执行**不要**开')
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--dump', action='store_true')
    ap.add_argument('--emit-body', metavar='PATH')
    ap.add_argument('--check-lng', action='store_true', help='只算 .lng 并与已部署的比（只读）')
    ap.add_argument('--no-write', action='store_true')
    args = ap.parse_args()

    asset_rio, jp_rio, zh_rio = Path(args.asset_rio), Path(args.jp_rio), Path(args.zh_rio)
    sc = dict(seam_entry(args.steam), steam=args.steam, orig=args.orig)
    new_stem = args.orig
    translations = {int(k): v for k, v in
                    json.loads(Path(args.translations).read_text(encoding='utf-8')).items()}
    renames = load_renames(args.rename_json)
    nametable = load_nametable(args.nametable_json)
    whole_blocks = ([(r[0], r[1]) for r in json.loads(Path(args.whole_blocks).read_text(
        encoding='utf-8'))] if args.whole_blocks else [])

    asset, jp = load(asset_rio), load(jp_rio)
    d = build(asset, jp, sc, translations, renames, args.strict_text_diff, whole_blocks,
              args.pilot_compat)
    meta = d['meta']

    print('\n需新译 %d 条：' % len(meta['restore']))
    for oi in sorted(meta['restore']):
        t = meta['recs_o'][oi][-1].fields.get('text')
        print('   idx %-3s %r => %r%s' % (oi, t, translations.get(oi, '（缺）'),
                                          '' if oi in translations else '  <<< 缺译文'))
    if d['missing']:
        print('!! 缺译文 idx %s' % d['missing'])

    badtxt = []
    ins2 = None
    try:
        ins2 = ws2disasm.disassemble(d['body'])
        cover = sum(i.size for i in ins2)
        cnt = lambda op: sum(1 for i in ins2 if i.opcode == op)      # noqa: E731
        print('\n自检 tile %d/%d %s；0x14=%d（期望 %d）；0x15=%d'
              % (cover, len(d['body']), 'OK' if cover == len(d['body']) else 'FAIL',
                 cnt(TEXT), meta['n_o'], cnt(NAME)))
        print('自检 机制 0x1c/0x01/0x02 = %d/%d/%d；0x1f=%d'
              % (cnt(0x1c), cnt(0x01), cnt(0x02), cnt(STOP)))
        _, recs2, _ = segment(ins2)
        badtxt = [oi for oi in sorted(meta['restore'])
                  if recs2[oi][-1].operands != meta['recs_o'][oi][-1].operands]
        print('自检 差分类 %d 条内嵌文本 == 原版：%s'
              % (len(meta['restore']), 'OK' if not badtxt else 'FAIL %s' % badtxt))
    except Exception as e:                                            # noqa: BLE001
        print('\n自检失败 %s: %s' % (type(e).__name__, e))
        sys.exit(2)

    if args.dump and ins2 is not None:
        _, recs2, _ = segment(ins2)
        print('\n重建后记录内顺序（文本应为末条）：')
        for oi in sorted({0, len(recs2) - 1} | set(sorted(meta['restore'])[:3])):
            if 0 <= oi < len(recs2):
                print('  #%-3d %s' % (oi, ' → '.join(ws2disasm.opcode_name(x.opcode)
                                                    for x in recs2[oi])))

    if args.check_lng:
        zh = arcbuild.read_raw(zh_rio)
        zh_dict = {nb.decode('utf-16le'): dd for nb, dd in zh}
        _, s_lng_raw = find_member({k: (k, v) for k, v in zh_dict.items()},
                                   sc['steam'] + '.lng')
        calc = lng.encode_lng(make_lng(meta, translations, lng.parse_lng(s_lng_raw)))
        cur_name = new_stem.lower() + '.lng'
        cur = zh_dict.get(cur_name) or zh_dict.get(cur_name.upper())
        print('\n--check-lng：计算出的 %s %d 字节；已部署 %s'
              % (cur_name, len(calc), ('%d 字节，%s' % (len(cur), '一致' if cur == calc else '不一致'))
                 if cur else '（不存在）'))
        if cur:
            print('   sha 计算=%s 部署=%s' % (sha(calc)[:16], sha(cur)[:16]))

    if args.emit_body:
        Path(args.emit_body).write_bytes(ws2.encode(d['body']))
        print('\n重建体已写出（未入库）：%s（%d 字节）' % (args.emit_body, len(d['body'])))

    blocked = (d['missing'] or d['fail'] or badtxt
               or meta['id_misalign'][0] or meta['id_misalign'][1])
    readonly = args.dry or args.no_write or args.emit_body or args.check_lng
    if readonly or blocked:
        print('\n未写入%s' % ('（有阻塞项）' if blocked else '（只读模式）'))
        if blocked:
            # 有阻塞项必须以非零退出码失败，否则上游会静默漏写
            sys.exit(1)
        return
    write_out(d, sc, new_stem, args, asset_rio, zh_rio, translations, nametable)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
