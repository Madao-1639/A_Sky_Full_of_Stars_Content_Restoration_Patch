"""接缝批处理驱动器：写入 / 只读重生 / 预验，三种模式共享同一份场景清单与施工输入。

前置：`tmp/seams/<orig>.translations.json` 已填、`verify_seam.py` 已验证 0 FAIL。

默认（写入模式）做的事：
  1. 逐场景跑 `script/seam/build_seam.py`（不带 --dry/--no-write）→ 建脚本 + 写 .lng + NameTable，
     并把**该场景 Steam 脚本的引用者**改指新脚本
  2. 全局清扫：把所有脚本里指向 `<已重建stem>_E` 的 `0x04/0x07` 改指 `<已重建stem>`
     （build_seam 只改"当前场景的引用者"，交叉引用需在此补）
  3. 提示含 EVRET 的脚本（需另跑 script/tools/fix_evret_offsets.py）

`--emit-only`：同一循环但全部带 `--emit-body`，只把脚本体重生到 `tmp/out/*.ws2`，
不写 asset/（原 emit_all.py）。

`--verify [--deployed]`：对 `tmp/out/` 里的重生脚本体逐个跑 verify_seam（带
--nametable-json），汇总 FAIL；`--deployed` 校验已部署形态（不传 --body）。
注意：verify_seam 靠 `--steam <stem>_E` 作基底重装；被旁路的 `*_E` 删除后跑不了，
故只在"接缝尚未落地"时使用（原 preverify_all.py）。

用法: python script/seam/apply_all_seams.py [--route hika] [--dry] | --emit-only | --verify [--deployed]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
from tool import arcbuild, ws2                                    # noqa: E402

SEAM = ROOT / 'resource' / 'seam-diffs.json'
SEAMS = ROOT / 'tmp' / 'seams'
NT = SEAMS / '_nametable.json'
ASSET_RIO = ROOT / 'asset' / 'Rio.arc'


def scene_list(route):
    scripts = [s for s in json.loads(SEAM.read_text(encoding='utf-8'))['scripts']
               if s['needs_rebuild'] and not s['done']]
    if route:
        scripts = [s for s in scripts if s['steam'].startswith('yozora_%s_' % route)]
    return scripts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--route')
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--emit-only', action='store_true',
                    help='只把脚本体重生到 tmp/out/（不写 asset/）')
    ap.add_argument('--verify', action='store_true',
                    help='对 tmp/out/ 中的脚本体逐个跑 verify_seam 汇总 FAIL')
    ap.add_argument('--deployed', action='store_true',
                    help='配合 --verify：校验已部署的脚本（不传 --body）')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')

    scripts = scene_list(a.route)

    if a.verify:
        verify_all(scripts, a)
        return 0

    if a.emit_only:
        emit_all(scripts)
        return 0

    # ---- 写入模式 ----
    missing = []
    for s in scripts:
        t = SEAMS / ('%s.translations.json' % s['orig'])
        if not t.exists():
            missing.append('%s(缺文件)' % s['orig'])
            continue
        d = json.loads(t.read_text(encoding='utf-8'))
        blank = [k for k, v in d.items() if not str(v).strip()]
        if blank:
            missing.append('%s(空值 %s)' % (s['orig'], blank[:5]))
    if missing:
        print('!! 以下场景译文未填，停手：%s' % missing)
        return 1

    fails = []
    for s in scripts:
        o = s['orig']
        cmd = [sys.executable, str(ROOT / 'script' / 'seam' / 'build_seam.py'),
               '--steam', s['steam'], '--orig', o,
               '--translations', str(SEAMS / ('%s.translations.json' % o)),
               '--rename-json', str(SEAMS / ('%s.rename.json' % o)),
               '--nametable-json', str(NT)]
        wb = SEAMS / ('%s.wholeblocks.json' % o)
        if wb.exists():
            cmd += ['--whole-blocks', str(wb)]
        if a.dry:
            cmd += ['--dry']
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        out = (r.stdout or '')
        # 构建器遇阻塞项会 print '!!' 并 return（退出码仍为 0）→ 必须按输出判定
        bad = r.returncode != 0 or '无法重定位' in out or '停手' in out or 'NameTable 缺映射' in out
        tag = 'FAIL' if bad else 'OK '
        print('[%s] %s' % (tag, o))
        for ln in out.splitlines():
            if any(k in ln for k in ('跳转', '成员', 'NameTable', '! ', '备份完成', 'FAIL', '停手')):
                print('    %s' % ln)
        if bad:
            fails.append((o, (r.stderr or out).strip()[-300:]))
    if a.dry:
        print('\n--dry：未写入')
        return 0
    if fails:
        print('\n!! 失败 %d 个 → 停手，不继续清扫：' % len(fails))
        for og, e in fails:
            print('  %s: %s' % (og, e))
        return 1

    # 2) 全局清扫：<已重建 stem>_E → <stem>
    rebuilt = {s['orig'].upper(): s['orig'].upper() for s in scripts}
    mem_s = arcbuild.read_raw(ASSET_RIO)
    out, changed, evret = [], {}, []
    for nb, d in mem_s:
        nm = nb.decode('utf-16le')
        if nm.upper().endswith('.WS2'):
            dec = ws2.decode(d)
            n = 0
            for stem_e, stem in rebuilt.items():
                for op in (0x04, 0x07):
                    old = bytes([op]) + stem_e.encode('ascii') + b'_E\x00'
                    new = bytes([op]) + stem.encode('ascii') + b'\x00'
                    if old in dec:
                        n += dec.count(old)
                        dec = dec.replace(old, new)
            if n:
                d = ws2.encode(dec)
                changed[nm] = n
            if b'EVRET' in dec:
                evret.append(nm)
        out.append((nb, d))
    if changed:
        arcbuild.write_arc(out, ASSET_RIO)
        arcbuild.verify(ASSET_RIO, expect_count=len(out))
    print('\n[清扫] 残留 `_E` 引用改写：%s' % (changed or '无'))
    if evret:
        print('[!] 含 EVRET 的脚本 %d 个 → 必须重跑 script/tools/fix_evret_offsets.py：%s'
              % (len(evret), evret))
    return 0


def emit_all(scripts):
    """只读重生脚本体到 tmp/out/（原 emit_all.py）。"""
    out_dir = ROOT / 'tmp' / 'out'
    out_dir.mkdir(parents=True, exist_ok=True)
    ok = bad = 0
    for s in scripts:
        o = s['orig']
        cmd = [sys.executable, str(ROOT / 'script' / 'seam' / 'build_seam.py'),
               '--steam', s['steam'], '--orig', o,
               '--translations', str(SEAMS / ('%s.translations.json' % o)),
               '--rename-json', str(SEAMS / ('%s.rename.json' % o)),
               '--nametable-json', str(NT),
               '--emit-body', str(out_dir / ('%s.ws2' % o))]
        wb = SEAMS / ('%s.wholeblocks.json' % o)
        if wb.exists():
            cmd += ['--whole-blocks', str(wb)]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        out = r.stdout or ''
        if r.returncode != 0 or '无法重定位' in out or '停手' in out:
            bad += 1
            print('[FAIL] %-26s %s' % (o, (r.stderr or out).strip()[-200:]))
        else:
            ok += 1
    print('重生成完成：OK %d / FAIL %d' % (ok, bad))


def verify_all(scripts, args):
    """逐场景跑 verify_seam 汇总 FAIL（原 preverify_all.py）。"""
    body_dir = ROOT / 'tmp' / 'out'
    rows, fails = [], []
    for s in scripts:
        o = s['orig']
        body = body_dir / ('%s.ws2' % o)
        if not args.deployed and not body.exists():
            rows.append((o, '无脚本体', -1))
            continue
        cmd = [sys.executable, str(ROOT / 'script' / 'seam' / 'verify_seam.py'),
               '--steam', s['steam'], '--orig', o,
               '--translations', str(SEAMS / ('%s.translations.json' % o)),
               '--rename-json', str(SEAMS / ('%s.rename.json' % o)),
               '--nametable-json', str(NT)]
        if not args.deployed:
            cmd += ['--body', str(body)]
        wb = SEAMS / ('%s.wholeblocks.json' % o)
        if wb.exists():
            cmd += ['--whole-blocks', str(wb)]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        out = r.stdout or ''
        nf = out.count('  [FAIL]')
        rows.append((o, 'OK' if nf == 0 else 'FAIL', nf))
        if nf:
            fails.append((o, [ln.strip() for ln in out.splitlines() if '[FAIL]' in ln]))
    for o, st, nf in rows:
        print('%-26s %-10s %s' % (o, st, ('%d 项' % nf) if nf >= 0 else ''))
    print('\n合计 %d 场景，FAIL %d 个' % (len(rows), len(fails)))
    for o, msgs in fails:
        print('  %s：%s' % (o, msgs))


if __name__ == '__main__':
    sys.exit(main())
