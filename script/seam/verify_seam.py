"""验收一个**差分接缝**脚本（通用化的 `tmp/verify_103e.py`）。

与构建器同一套输入；默认验收 `asset/Rio.arc` 里**已部署**的成员（`--body PATH` 可验收未入库的重建体）。

核心不变式：
  ① 文本记录数 == 原版句数；id 连续 `0..N-1`；重建体 100% tile、无空洞
  ② **差分类记录的演出指令 == 原版**（忽略 keep_steam 类、`0x14`/`0x15`；`0x11` 只比秒数）
  ③ **差分类记录的内嵌文本 == 原版**
  ④ `.lng` 引号形态（对话 `「…」%K%P`、旁白无引号、字面 `\\n` 个数与原版一致）
  ⑤ 跳过已读机制组的邻接与跳转目标正确；`0xff` 沿用 Steam 原值
  ⑥ 说话人前缀全部命中 `NameTable.txt`（含 --nametable-json 的追加）
  ⑦ 资源改名：`--rename-json` 涉及的资源在脚本里一律用隔离名

用法:
  python script/seam/verify_seam.py --steam ... --orig ... --translations ... [--rename-json ...]
      [--nametable-json ...] [--whole-blocks ...] [--pilot-compat] [--body PATH]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
import build_seam as B                                            # noqa: E402
from tool import arcbuild, lng, ws2, ws2disasm                     # noqa: E402

TEXT, NAME, STOP = 0x14, 0x15, 0x1f
fails, warns = [], []


def check(ok, msg):
    print('  [%s] %s' % ('OK ' if ok else 'FAIL', msg))
    if not ok:
        fails.append(msg)


def key(ins, iso2bare):
    if ins.opcode == B.TIMER:
        return (ins.opcode, ins.fields.get('seconds'))
    ops = ins.operands
    for iso, bare in iso2bare:                       # 新脚本的隔离名 → 裸名，便于与原版比
        for o in B._ascii_variants(iso):
            ops = ops.replace(o, bare)
    return (ins.opcode, ops)


def mech_targets(rec):
    """记录内被**机制类控制流**（`0x01`/`0x02`/`0x06`）跳转引用的指令偏移。

    「Steam 新增的、不影响演出的机制一律保留」的必然结果：跳过已读机制组 `[0x1c][0x01][0x02]`
    连同它跳转所指的指令（如 Steam 版独有的 `0x1f StopMusic`）是**一个整体**——当原版在该处
    没有对应指令时，构建器会把 Steam 的那条一并取回（见 `build_seam.py` 的"机制跳转闭包"）。
    这些被机制引用的指令不属于"演出回原版"的范畴，故不计入 ① 的比对；否则会与"保留机制"冲突。
    """
    tgt = set()
    for i in rec:
        if i.opcode in (0x01, 0x02, 0x06):
            for t in B._jump_targets(i):
                if t:
                    tgt.add(t)
    return tgt


def perf_pair(o_rec, n_rec, iso2bare):
    """返回 (原版侧演出键序列, 新侧演出键序列) 供 ① 比对。

    新侧**允许**比原版多出"被机制类控制流引用、且原版该处没有"的指令：

    「Steam 新增的、不影响演出的机制一律保留」的必然结果——跳过已读机制组
    `[0x1c][0x01][0x02]` 连同它跳转所指的指令（如 Steam 版独有的 `0x1f StopMusic`）是**一个
    整体**；当原版在该处没有对应指令时，构建器会把 Steam 的那条一并取回（见 `build_seam.py`
    的"机制跳转闭包"）。这些被机制引用的指令不属于"演出回原版"的范畴，故不计入 ①，
    否则会与"保留机制"这条用户裁定直接冲突。

    原版侧照常全比；新侧仅把"机制引用 **且** 原版没有"的那几条剔除（按内容比对，
    故规范形态下重定向到原版 StopMusic 的情形不受影响）。
    """
    ex = {TEXT, NAME} | B.KEEP_STEAM
    po = [key(i, iso2bare) for i in o_rec if i.opcode not in ex]
    mt = mech_targets(n_rec)
    pn = []
    for i in n_rec:
        if i.opcode in ex:
            continue
        k = key(i, iso2bare)
        if i.offset in mt and k not in po:
            continue                          # 机制引用、且原版没有 → 允许存在
        pn.append(k)
    return po, pn


def perf(rec, iso2bare):
    ex = {TEXT, NAME} | B.KEEP_STEAM
    return [key(i, iso2bare) for i in rec if i.opcode not in ex]


def find_spelling(ins_list, name_bytes):
    """在指令操作数里找出 name 的实际拼写字节（对齐大小写惯例）。"""
    for i in ins_list:
        p = i.operands.upper().find(name_bytes.upper())
        if p >= 0:
            return i.operands[p:p + len(name_bytes)]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--steam', required=True)
    ap.add_argument('--orig', required=True)
    ap.add_argument('--translations', required=True)
    ap.add_argument('--rename-json')
    ap.add_argument('--nametable-json')
    ap.add_argument('--whole-blocks')
    ap.add_argument('--pilot-compat', action='store_true')
    ap.add_argument('--body')
    ap.add_argument('--asset-rio', default=str(B.ASSET_RIO))
    ap.add_argument('--jp-rio', default=str(B.JP_RIO))
    ap.add_argument('--zh-rio', default=str(B.ZH_RIO))
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')

    sc = dict(B.seam_entry(args.steam), steam=args.steam, orig=args.orig)
    new_stem = args.orig
    translations = {int(k): v for k, v in
                    json.loads(Path(args.translations).read_text(encoding='utf-8')).items()}
    renames = B.load_renames(args.rename_json)
    nametable = B.load_nametable(args.nametable_json)
    whole_blocks = ([(r[0], r[1]) for r in json.loads(Path(args.whole_blocks).read_text(
        encoding='utf-8'))] if args.whole_blocks else [])

    asset_rio, jp_rio, zh_rio = Path(args.asset_rio), Path(args.jp_rio), Path(args.zh_rio)
    asset, jp = B.load(asset_rio), B.load(jp_rio)

    if args.body:
        raw = ws2.encode(ws2.decode(Path(args.body).read_bytes()))
        src = args.body
    else:
        _, raw = B.find(asset, new_stem)
        src = '%s 的 %s.ws2（已部署）' % (asset_rio.name, new_stem)

    _, o_raw = B.find(jp, sc['orig'])
    _, s_raw = B.find(asset, sc['steam'])
    S = ws2disasm.disassemble(ws2.decode(s_raw))
    O = ws2disasm.disassemble(ws2.decode(o_raw))
    N = ws2disasm.disassemble(ws2.decode(raw))
    _, recs_o, _ = B.segment(O)
    _, recs_n, _ = B.segment(N)
    _, recs_s, _ = B.segment(S)
    meta = B.build_plan(asset, jp, sc, False, whole_blocks, args.pilot_compat)[1]
    o2s = meta['o2s']
    restore = sorted(meta['restore'])
    # 把新脚本的隔离名按**原版脚本的实际拼写**归一成裸名后比较（避免大小写误判）
    o_ins = [i for r in recs_o for i in r]
    iso2bare = []
    for old, new in renames:
        nb = old.encode('shift_jis')
        bare = find_spelling(o_ins, nb) or nb
        for v in B._ascii_variants(new.encode('shift_jis')):
            if v:
                iso2bare.append((v, bare))
    print('验收对象：%s' % src)
    print('原版记录 %d；重建记录 %d；重建指令 %d' % (len(recs_o), len(recs_n), len(N)))

    print('\n## 结构')
    check(len(recs_n) == len(recs_o), '文本记录 %d 条（== 原版 %d）' % (len(recs_n), len(recs_o)))
    ids = [r[-1].fields.get('id') for r in recs_n]
    check(ids == list(range(len(recs_n))), '文本 id 连续 0..%d' % (len(recs_n) - 1))
    body = ws2.decode(raw)
    cover = sum(i.size for i in N)
    starts = {i.offset for i in N}
    ends = {i.offset + i.size for i in N}
    check(cover == len(body) and min(starts) == 0
          and starts | {len(body)} == ends | {0},
          '100%% tile、无空洞（%d 字节 / %d 指令）' % (len(body), len(N)))

    print('\n## ① 差分类记录的演出指令 == 原版（逐记录逐指令）')
    bad = []
    for oi, o_rec in enumerate(recs_o):
        n_rec = recs_n[oi]
        po, pn = perf_pair(o_rec, n_rec, iso2bare)
        if po != pn:
            bad.append(oi)
    check(not bad, '演出逐项一致（忽略 keep_steam、机制引用的指令 与资源改名）' if not bad
          else '不一致的记录：%s' % bad[:8])

    print('\n## ② 差分类记录的内嵌文本 == 原版')
    badtxt = []
    for oi, o_rec in enumerate(recs_o):
        tn = recs_n[oi][-1].fields.get('text')
        to = o_rec[-1].fields.get('text')
        if oi in meta['restore']:
            if tn != to:
                badtxt.append(oi)
        elif o2s.get(oi) is not None:
            if tn != recs_s[o2s[oi]][-1].fields.get('text'):
                badtxt.append(oi)
    check(not badtxt, '差分类 %d 条内嵌文本 == 原版；共用句 == Steam%s'
          % (len(restore), '' if not badtxt else '（不一致 %s）' % badtxt[:8]))

    print('\n## ③ 语音名（差分类 == 原版）')
    badv = [oi for oi in restore if B.voice_sig(recs_o[oi]) != B.voice_sig(recs_n[oi])]
    check(not badv, '差分类语音名 == 原版%s' % ('' if not badv else '（不一致 %s）' % badv))

    print('\n## ④ 跳过已读机制组 / 0xff')
    groups, orph = [], 0
    k = 0
    while k + 3 <= len(N):
        if [N[k + j].opcode for j in range(3)] == [0x1c, 0x01, 0x02]:
            if k + 6 < len(N) and N[k + 3].opcode == STOP:
                jt = int.from_bytes(N[k + 2].operands[0:4], 'little')
                ca = int.from_bytes(N[k + 1].operands[7:11], 'little')
                cb = int.from_bytes(N[k + 1].operands[11:15], 'little')
                after = N[k + 3].offset + N[k + 3].size
                groups.append((N[k].offset, jt == after and ca == N[k + 3].offset
                               and cb == after))
            else:
                orph += 1
            k += 3
        else:
            k += 1
    check(groups and all(g[1] for g in groups) and orph == 0,
          '机制组 %d 处、邻接与跳转目标正确、游离 %d' % (len(groups), orph))
    ff_n = [i for i in N if i.opcode == 0xff]
    ff_s = [i for i in S if i.opcode == 0xff]
    check(len(ff_n) == len(ff_s) == 1 and ff_n[0].operands == ff_s[0].operands,
          '0xff == Steam（新 %s / Steam %s）'
          % (ff_n[0].operands.hex() if ff_n else None, ff_s[0].operands.hex() if ff_s else None))
    check(N[-1].opcode == 0xff, '0xff 为末条')

    print('\n## ⑤ 文本拆分（共用句取 Steam / 差分类取原版）')
    n_shared = sum(1 for oi in range(len(recs_o)) if oi not in meta['restore'])
    unpaired = meta['audit']['unpaired']
    check(True, '差分类 %d（未配对 %d ∪ 语义 %d ∪ 整块 %d）/ 共用句 %d'
          % (len(restore), len(unpaired), len(meta['audit']['semantic_records']),
             len(meta['audit']['whole_blocks']), n_shared))

    print('\n## ⑥ .lng（已部署时）')
    zh_dict = {nb.decode('utf-16le'): dd for nb, dd in arcbuild.read_raw(zh_rio)}
    lng_name = new_stem.lower() + '.lng'
    try:
        _, s_lng_raw = B.find_member({k: (k, v) for k, v in zh_dict.items()},
                                     sc['steam'] + '.lng')
        calc = B.make_lng(meta, translations, lng.parse_lng(s_lng_raw))
        check(len(calc) == len(recs_o), '.lng 条数 %d（== 原版 %d）' % (len(calc), len(recs_o)))
        check(lng.parse_lng(lng.encode_lng(calc)) == calc, '.lng 长度表自洽')
        cur = zh_dict.get(lng_name) or zh_dict.get(lng_name.upper())
        if cur:
            check(lng.parse_lng(cur) == calc, '.lng 与已部署逐条一致')
        else:
            warns.append('.lng %s 尚未部署（跳过比对）' % lng_name)
            print('  [SKIP] .lng %s 尚未部署' % lng_name)
        nl = lng.parse_lng(cur) if cur else calc
    except SystemExit as e:
        warns.append(str(e))
        print('  [SKIP] %s' % e)
        nl = None

    print('\n## ⑦ 引号形态 / 字面 \\n 个数（差分类）')
    badq, badn = [], []
    for oi in restore:
        jp = recs_o[oi][-1].fields.get('text') or ''
        zh = (nl[oi] if nl and oi < len(nl) else translations.get(oi, ''))
        dlg = jp.startswith('「')
        # 译文与**官中**统一：对话用 “”（判定依据是内嵌日文以「」开头）；旁白不加引号
        ok = ((zh.startswith('“') and zh.endswith('”%K%P')) if dlg
              else not zh.startswith('“'))
        if not ok:
            badq.append((oi, jp[:14], zh[:16]))
        if zh.count('\\n') != jp.count('\\n'):
            badn.append((oi, jp.count('\\n'), zh.count('\\n')))
    check(not badq, '引号形态（对话 “”、旁白不加）%s'
          % ('' if not badq else '：%s' % badq))
    check(not badn, '字面 \\n 个数与原版一致%s' % ('' if not badn else '：%s' % badn))

    print('\n## ⑧ 说话人前缀全部命中 NameTable')
    nt_raw = zh_dict.get('NameTable.txt') or zh_dict.get('NAMETABLE.TXT') or b''
    nt = nt_raw.decode('utf-16le')
    keys = {ln.split('\t')[0] for ln in nt.split('\r\n') if '\t' in ln} | set(nametable)
    pre = sorted({i.fields.get('prefix') or '' for i in N if i.opcode == NAME})
    miss = [p for p in pre if p and p not in keys]
    check(not miss, '前缀 %d 种全部命中%s' % (len(pre), '' if not miss else '；未命中 %s' % miss))

    print('\n## ⑨ 资源改名')
    if renames:
        want = {new.encode('shift_jis') for _, new in renames}
        olds = [B._ascii_variants(o.encode('shift_jis')) for o, _ in renames]
        seen_old, seen_new = 0, 0
        for i in N:
            if i.opcode != 0x34:
                continue
            if any(v in i.operands for v in want):       # 隔离名本身含裸名子串 → 先判隔离名
                seen_new += 1
            elif any(any(v in i.operands for v in vs) for vs in olds):
                seen_old += 1
        check(seen_old == 0, '裸名引用已全部改为隔离名（残留 %d 处）' % seen_old)
        check(seen_new > 0, '隔离名引用 %d 处' % seen_new)
    else:
        print('  （未提供 --rename-json，跳过）')

    print('\n===== 结论：%d 项 FAIL =====' % len(fails))
    for f in fails:
        print('  FAIL %s' % f)
    for w in warns:
        print('  warn %s' % w)
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
