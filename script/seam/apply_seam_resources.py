"""批量资源补入：把接缝重建所需的原版成员追加进 asset/ 对应归档（只做资源，不动脚本）。

计划来源（自动推导，无需手维护）：
  A. Steam 缺失项（tmp/seam_resources/*.json 里 verdict=STEAM_MISSING）→ 补入原名；
     来源 = 日文原版（../抬头看看吧看那天上的繁星）里**同名归档**中的同名成员；
     目标 = asset/<同名归档>。
  B. 真冲突的隔离副本（决策=真冲突、隔离名非空）→ 若尚未部署，则补入并改用隔离名。
     （隔离名大小写按目标归档惯例；目前只需 HIK_91L/S → Chip3.arc。）

幂等：已存在且与源一致 → 跳过；已存在但与源不一致 → 停手（不覆盖）。
写入走同目录临时文件 + os.replace；分段流式，全程不把归档读进内存。

用法:
  python script/seam/apply_seam_resources.py --plan     # 只读清点报告（原 seam_deploy.py）：
                                                   #   缺失/隔离副本按"被 N 个接缝引用"汇总，
                                                   #   误报/本地化/待定的排除清单与「待定」警告，
                                                   #   --names-out 写待补名单
  python script/seam/apply_seam_resources.py            # dry-run（只报计划与体量）
  python script/seam/apply_seam_resources.py --apply    # 实际写入（含备份 + 回读校验）
"""
import argparse
import hashlib
import json
import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from tool import arcbuild, arcstream                                   # noqa: E402
# --- 归档读写 helper（原为 add_pilot_resources 提供，已内联以保持自洽）-------------
CHUNK = 1 << 22
HEADER = struct.Struct('<II')
ENTRY = struct.Struct('<II')


def sha256_range(path, offset, size, chunk=CHUNK):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        fh.seek(offset)
        left = size
        while left:
            buf = fh.read(min(chunk, left))
            if not buf:
                raise ValueError('unexpected EOF in %s (want %d at %d)' % (path, size, offset))
            h.update(buf)
            left -= len(buf)
    return h.hexdigest()


def sha256_file(path, chunk=CHUNK):
    return sha256_range(path, 0, os.path.getsize(path), chunk)


def index_by_name(path):
    """(data_start, ordered_index, {NAME_UPPER: [(name, rel, size)]})。"""
    data_start, index = arcstream.read_index(path)
    by_name = {}
    for nb, rel, size in index:
        by_name.setdefault(nb.decode('utf-16le').upper(), []).append((nb, rel, size))
    return data_start, index, by_name


def append_members(target, additions, tmp_suffix='.tmp_add'):
    """把 additions = [(name_bytes, src_path, src_offset, size)] 追加到归档末尾（流式）。

    表项偏移是"相对 8+table_size"的，表变长只会把数据区整体后移，老成员偏移不变 ——
    故新文件 = 新表头 + 新表 + 原数据区原样 + 新成员数据。
    """
    data_start, index, _by = index_by_name(target)
    old_count = len(index)
    old_end = os.path.getsize(target)
    run = 0
    for _nb, rel, size in index:
        if rel != run:
            raise SystemExit('FATAL: %s 成员表不连续（rel=%d 期望 %d）' % (target, rel, run))
        run += size
    if data_start + run != old_end:
        raise SystemExit('FATAL: %s 末尾有 %d 字节多余数据' % (target, old_end - data_start - run))
    table = bytearray()
    rel = run
    for nb, old_rel, size in index:
        table += ENTRY.pack(size, old_rel) + nb + b'\0\0'
    for nb, _src, _off, size in additions:
        table += ENTRY.pack(size, rel) + nb + b'\0\0'
        rel += size
    tmp = Path(str(target) + tmp_suffix)
    try:
        with open(target, 'rb') as src, open(tmp, 'wb') as dst:
            dst.write(HEADER.pack(old_count + len(additions), len(table)))
            dst.write(table)
            src.seek(data_start)
            left = old_end - data_start
            while left:
                buf = src.read(min(CHUNK, left))
                if not buf:
                    raise ValueError('unexpected EOF copying %s' % target)
                dst.write(buf)
                left -= len(buf)
            for _nb, src_path, src_off, size in additions:
                with open(src_path, 'rb') as f:
                    f.seek(src_off)
                    left = size
                    while left:
                        buf = f.read(min(CHUNK, left))
                        if not buf:
                            raise ValueError('unexpected EOF in %s at %d' % (src_path, src_off))
                        dst.write(buf)
                        left -= len(buf)
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()
    return old_count + len(additions)

SRC_DIR = ROOT.parent / '抬头看看吧看那天上的繁星'
ASSET = ROOT / 'asset'
CACHE = ROOT / 'tmp' / 'seam_resources'
DEC = ROOT / 'resource' / 'resource-decisions.json'   # 权威表（resource/README 消费者契约）；tmp/ 下的旧副本已弃用
BACKUP_SUFFIX = '.before_batch'
log = lambda m: print(m, flush=True)


def backup_once(target):
    backup = Path(str(target) + BACKUP_SUFFIX)
    if backup.exists():
        log('    [SKIP] 备份已存在: %s' % backup.name)
        return backup
    log('    [BACKUP] %s -> %s' % (target.name, backup.name))
    with open(target, 'rb') as s, open(backup, 'wb') as d:
        while True:
            buf = s.read(CHUNK)
            if not buf:
                break
            d.write(buf)
    a, b = sha256_file(target), sha256_file(backup)
    if a != b:
        raise SystemExit('FATAL: 备份校验失败 %s' % target)
    log('    [BACKUP OK] sha256=%s' % a[:16])
    return backup


_SRC_INDEX = None


def src_locate(dirpath, wanted):
    """在 dirpath 的归档里找 wanted（大小写不敏感），返回 (arc_path, name_bytes, off, size)。

    整个目录的成员表只读一次并缓存（否则 265 个名字 × 11 个归档会反复读表）。
    """
    global _SRC_INDEX
    if _SRC_INDEX is None:
        _SRC_INDEX = {}
        for arc in sorted(dirpath.glob('*.arc')):
            ds, _idx, by = index_by_name(arc)
            for key, hits in by.items():
                if key in _SRC_INDEX:
                    raise SystemExit('FATAL: %s 在多个来源归档中重复：%s' % (key, arc))
                nb, rel, size = hits[0]
                _SRC_INDEX[key] = (arc, nb, ds + rel, size)
    return _SRC_INDEX.get(wanted.upper())


def build_plan():
    """[(target_arc_name, write_bytes, write_str, src_arc_path, src_nb, src_off, src_size, kind)]

    写入名一律**沿用源成员名的字节形态**（= 该归档的既有惯例）：
      - 缺失项：直接用源名
      - 隔离副本：把源名的 stem 换成隔离名 stem，保留源名的扩展名大小写
        （如源 `HIK_12L.pna` + 隔离 `HIK_91L.PNA` → 写 `HIK_91L.pna`）
    """
    names = set()
    for f in sorted(CACHE.glob('*.json')):
        for r in json.loads(f.read_text(encoding='utf-8')):
            if r['verdict'] == 'STEAM_MISSING':
                names.add(r['name'])
    dec = json.loads(DEC.read_text(encoding='utf-8'))
    plan, missing_src = [], []
    for n in sorted(names):
        loc = src_locate(SRC_DIR, n)
        if not loc:
            missing_src.append(n)
            continue
        arc, nb, off, size = loc
        plan.append((arc.name, nb, nb.decode('utf-16le'), arc, nb, off, size, 'missing'))
    # 真冲突隔离副本（未部署者）
    target_names = set()
    for arc in sorted(ASSET.glob('*.arc')):
        for nm in arcstream.names(arc):
            target_names.add(nm.upper())
    for n, v in sorted(dec.items()):
        if v.get('verdict') != '真冲突' or not v.get('isolation_name'):
            continue
        iso = v['isolation_name']
        if iso.upper() in target_names:
            continue
        loc = src_locate(SRC_DIR, n)
        if not loc:
            missing_src.append(n)
            continue
        arc, nb, off, size = loc
        src_name = nb.decode('utf-16le')
        stem = iso.rsplit('.', 1)[0]
        ext = src_name.rsplit('.', 1)[1] if '.' in src_name else ''
        write = stem + ('.' + ext if ext else '')
        plan.append((arc.name, write.encode('utf-16le'), write, arc, nb, off, size, 'isolate'))
    return plan, missing_src, len(names)


def load_asset_names():
    present = {}
    for arc in sorted(ASSET.glob('*.arc')):
        try:
            for nm in arcstream.names(arc):
                present.setdefault(nm.upper(), []).append(arc.name)
        except Exception as e:
            log('  (%s 读索引失败 %s)' % (arc.name, type(e).__name__))
    return present


def plan_report(args):
    """只读清点（原 seam_deploy.py）：施工前置的资源部署报告，不写任何文件。"""
    from collections import Counter
    dec = json.loads(DEC.read_text(encoding='utf-8'))
    present = load_asset_names()

    miss, iso, skipped = {}, {}, {}
    for f in sorted(CACHE.glob('*.json')):
        for r in json.loads(f.read_text(encoding='utf-8')):
            n, v = r['name'], r['verdict']
            if v == 'STEAM_MISSING':
                miss.setdefault(n.upper(), {'name': n, 'src_arc': r.get('alt_arc'), 'by': set()})
                miss[n.upper()]['by'].add(f.stem)
            elif v == 'CONFLICT':
                d = dec.get(n, {})
                if d.get('verdict') == '真冲突' and d.get('isolation_name'):
                    iso.setdefault(n.upper(), {'name': n, 'iso': d['isolation_name'],
                                               'src_arc': r.get('alt_arc') or r.get('arc'),
                                               'by': set()})
                    iso[n.upper()]['by'].add(f.stem)
                else:
                    skipped[n.upper()] = d.get('verdict', '?')

    log('=== 需补入（Steam 缺失，写原名）：%d 种 ===' % len(miss))
    n_new = n_have = 0
    for k, v in sorted(miss.items()):
        have = present.get(k)
        if have:
            n_have += 1
            if args.present:
                log('  (已有) %-22s in %s' % (v['name'], have))
        else:
            n_new += 1
            log('  %-22s ← %-12s 被 %d 个接缝引用' % (v['name'], v['src_arc'], len(v['by'])))
    log('  → 缺 %d，已有 %d' % (n_new, n_have))
    if args.names_out:
        todos = [v['name'] for k, v in sorted(miss.items()) if not present.get(k)]
        Path(args.names_out).write_text('\n'.join(todos) + '\n', encoding='utf-8')
        log('  （已写出待补名单 %s，%d 条）' % (args.names_out, len(todos)))

    log('\n=== 需补入 + 改隔离名（真冲突）：%d 种 ===' % len(iso))
    for k, v in sorted(iso.items()):
        iso_have = present.get(v['iso'].upper())
        log('  %-22s ← %-12s → %-24s %s' % (
            v['name'], v['src_arc'], v['iso'],
            ('（隔离副本已在 %s）' % iso_have if iso_have else '（需新增）')))

    log('\n=== 不引入（误报/本地化/待定）：%d 种 ===' % len(skipped))
    log('  %s' % dict(Counter(skipped.values())))
    todo = sorted(k for k, v in skipped.items() if v == '待定')
    if todo:
        log('\n⚠ 以下 %d 个「待定」被接缝脚本引用，需人工核（不处理则会显示 Steam 改过的版本）：' % len(todo))
        for k in todo:
            log('   %s' % k)
    log('\n被最多接缝引用的缺失项（前 15）：')
    for k, v in sorted(miss.items(), key=lambda kv: -len(kv[1]['by']))[:15]:
        log('  %-22s %d' % (v['name'], len(v['by'])))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', action='store_true',
                    help='只读清点报告（原 seam_deploy.py）：缺失/隔离/排除项 + 待定警告')
    ap.add_argument('--present', action='store_true', help='配合 --plan：显示"已存在"的项')
    ap.add_argument('--names-out', help='配合 --plan：把"需补入"的全部名字写到该文件（每行一个）')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--limit', type=int, help='只处理前 N 条（调试用）')
    a = ap.parse_args()

    if a.plan:
        plan_report(a)
        return 0

    plan, missing_src, n_missing = build_plan()
    if a.limit:
        plan = plan[:a.limit]
    log('=' * 84)
    log('资源补入计划：STEAM_MISSING %d 项 + 隔离副本 %d 项 = %d 项'
        % (n_missing, len(plan) - n_missing, len(plan)))
    log('=' * 84)
    from collections import defaultdict
    byarc = defaultdict(lambda: [0, 0])
    for tgt, wnb, wstr, src, nb, off, size, kind in plan:
        byarc[tgt][0] += 1
        byarc[tgt][1] += size
    total = 0
    for arc, (cnt, byt) in sorted(byarc.items()):
        total += byt
        log('  %-14s %3d 项  %10.1f MB' % (arc, cnt, byt / 1e6))
    log('  合计新增 %.1f MB' % (total / 1e6))
    if missing_src:
        log('\n⚠ 来源缺失 %d 项：%s' % (len(missing_src), missing_src[:20]))
    # 示例
    log('\n示例（前 8 项）：')
    for tgt, wnb, wstr, src, nb, off, size, kind in plan[:8]:
        log('  %-14s %-24s ← %s/%s (%d bytes, %s)'
            % (tgt, wstr, src.parent.name, nb.decode('utf-16le'), size, kind))
    log('\n非语音项（全部）：')
    for tgt, wnb, wstr, src, nb, off, size, kind in plan:
        if not wstr.lower().endswith('.ogg'):
            log('  %-14s %-24s %9d bytes  %s' % (tgt, wstr, size, kind))

    # 幂等预检（只读）：已在目标归档里的项，字节是否与源一致
    log('\n幂等预检（已在位项与源比对）：')
    tgt_ix = {}
    n_present = n_ok = n_bad = 0
    for tgt, wnb, wstr, src, nb, off, size, kind in plan:
        if tgt not in tgt_ix:
            tgt_ix[tgt] = index_by_name(ASSET / tgt)
        ds, _idx, by = tgt_ix[tgt]
        hits = by.get(wstr.upper())
        if not hits:
            continue
        n_present += 1
        got = sha256_range(ASSET / tgt, ds + hits[0][1], hits[0][2])
        want = sha256_range(src, off, size)
        if got == want:
            n_ok += 1
        else:
            n_bad += 1
            log('  [MISMATCH] %-14s %-24s 目标 %d bytes / 源 %d bytes'
                % (tgt, wstr, hits[0][2], size))
    log('  已在位 %d 项：一致 %d，不一致 %d' % (n_present, n_ok, n_bad))
    if n_bad:
        log('  ⚠ 有不一致项；--apply 会在这些归档上 FATAL（需先定夺）')
    if not a.apply:
        log('\n（dry-run，未写入；加 --apply 实际执行）')
        return 0

    # 按目标归档分组，逐个处理
    groups = defaultdict(list)
    for tgt, wnb, wstr, src, nb, off, size, kind in plan:
        groups[tgt].append((wnb, wstr, src, off, size))
    log('\n[备份]')
    for tgt in sorted(groups):
        backup_once(ASSET / tgt)

    log('\n[幂等检查 + 追加]')
    for tgt in sorted(groups):
        target = ASSET / tgt
        _ds, _idx, by = index_by_name(target)
        adds = []
        for wnb, wstr, src, off, size in groups[tgt]:
            hits = by.get(wstr.upper())
            if hits:
                got = sha256_range(target, _ds + hits[0][1], hits[0][2])
                want = sha256_range(src, off, size)
                if got != want:
                    raise SystemExit('FATAL: %s 已有 %s 但字节不一致，停手' % (tgt, wstr))
                log('    %-12s %-24s SKIP(一致)' % (tgt, wstr))
                continue
            adds.append((wnb, src, off, size))
        if adds:
            before = len(index_by_name(target)[1])
            after = append_members(target, adds, tmp_suffix='.tmp_seamres')
            log('    %-12s %d -> %d（追加 %d）' % (tgt, before, after, len(adds)))
        else:
            log('    %-12s 无需写入' % tgt)

    log('\n[结构校验]')
    bad = 0
    for tgt in sorted(groups):
        count, size, end = arcbuild.verify(ASSET / tgt)
        trail = size - end
        ok = trail == 0
        bad += 0 if ok else 1
        log('    [%s] %-12s 成员 %d, %d bytes, trailing=%d'
            % ('OK' if ok else 'FAIL', tgt, count, size, trail))
    log('\n结论: %s' % ('OK' if not bad and not missing_src else 'FAIL'))
    return 0 if not bad and not missing_src else 1


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
