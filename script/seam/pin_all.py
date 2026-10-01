"""为全部待重建接缝生成 pinned 施工单，并汇总"整块还原候选"（供用户一次裁定）。

用法: python script/seam/pin_all.py [--route hika|saya|ori|koro] [--summary-only]
输出: tmp/seams/ 下的每场景文件 + tmp/seams/_SUMMARY.md（候选汇总）
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
SEAM = ROOT / 'resource' / 'seam-diffs.json'
OUT = ROOT / 'tmp' / 'seams'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--route')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    OUT.mkdir(parents=True, exist_ok=True)

    scripts = [s for s in json.loads(SEAM.read_text(encoding='utf-8'))['scripts']
               if s['needs_rebuild'] and not s['done']]
    if a.route:
        scripts = [s for s in scripts if s['steam'].startswith('yozora_%s_' % a.route)]

    rows, details = [], []
    for s in scripts:
        wb = OUT / ('%s.wholeblocks.json' % s['orig'])
        cmd = [sys.executable, str(ROOT / 'script' / 'seam' / 'pin_translations.py'),
               '--steam', s['steam'], '--orig', s['orig']]
        if wb.exists():
            cmd += ['--whole-blocks', str(wb)]
        tj0 = OUT / ('%s.translations.json' % s['orig'])
        if tj0.exists():
            cur = json.loads(tj0.read_text(encoding='utf-8'))
            if not any(v for v in cur.values()):
                cmd += ['--force']          # 模板仍是空的 → 可安全重生成（整块变了会扩集合）
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        if r.returncode != 0:
            print('  [FAIL] %-30s %s' % (s['steam'], (r.stderr or '').strip()[-200:]))
            continue
        tj = OUT / ('%s.translations.json' % s['orig'])
        rj = OUT / ('%s.rename.json' % s['orig'])
        cj = OUT / ('%s.wholeblocks.candidates.json' % s['orig'])
        n_t = len(json.loads(tj.read_text(encoding='utf-8'))) if tj.exists() else 0
        n_r = len([k for k in json.loads(rj.read_text(encoding='utf-8')) if not k.startswith('_')])
        cands = json.loads(cj.read_text(encoding='utf-8')) if cj.exists() else []
        import re
        m = re.search(r'⚠ (\d+) 项待裁定', r.stdout or '')
        if m and int(m.group(1)):
            md = (OUT / ('%s.worklist.md' % s['orig'])).read_text(encoding='utf-8')
            pend = [ln for ln in md.splitlines() if ln.startswith('- 资源')]
        else:
            pend = []
        rows.append((s['steam'], s['orig'], n_t, n_r, len(cands), pend))
        if cands:
            md = (OUT / ('%s.worklist.md' % s['orig'])).read_text(encoding='utf-8')
            blk = [ln for ln in md.splitlines() if ln.startswith('- ') and 'orig=' in ln]
            details.append((s['orig'], blk))

    print('\n%-32s %-26s %5s %5s %5s %4s' % ('Steam 脚本', '新脚本', '待译', '改名', '整块候选', '待定'))
    for st, og, t, r_, c, p in rows:
        print('%-32s %-26s %5d %5d %5d %4d' % (st, og, t, r_, c, len(p)))
    print('\n合计：%d 场景，待译 %d 条，整块候选 %d 个，待定 %d 项'
          % (len(rows), sum(r[2] for r in rows), sum(r[4] for r in rows),
             sum(len(r[5]) for r in rows)))
    if any(r[5] for r in rows):
        print('\n== 待裁定资源明细 ==')
        for st, og, _t, _r, _c, pend in rows:
            for ln in pend:
                print('  %-26s %s' % (og, ln))

    lines = ['# 整块还原候选汇总（供用户一次裁定）', '',
             '「同时含还原与保留」的 text 块：块内有 1:1 语音配对的记录（应保留 Steam）、也有需还原的。',
             '**不做整块还原的话，正文不会少，但那几条按"同语音即同句"保留 Steam**——若块内确实是被 Steam 改写，则需整块还原。', '']
    for og, blk in details:
        lines.append('## `%s`（%d 块）' % (og, len(blk)))
        lines += blk
        lines.append('')
    (OUT / '_SUMMARY.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('候选汇总 → %s' % (OUT / '_SUMMARY.md'))


if __name__ == '__main__':
    main()
