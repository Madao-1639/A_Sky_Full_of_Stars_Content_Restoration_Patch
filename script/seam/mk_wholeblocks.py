"""按判据生成各场景的 `<orig>.wholeblocks.json`（`--whole-blocks` 的输入）。

判据（已在 103e 与 3 个样本上核过）：
  - 块内 `orig_n != steam_n`（句数不同）→ **整块还原**（含块内语音配对的记录）
  - 块内 `orig_n == steam_n`         → **保持拆分**（1:1 按位置配对，语义平行；被 Steam 替换的那条
    本就在"还原"集合里）
理由：句数不同的块里，"保留"是按**空语音签名**按位置凑的配对，不可信；实测这些记录往往是
Steam **改写/弱化过的同一段**（如 110b 68–72 的露骨旁白），须一并还原。

用法: python script/seam/mk_wholeblocks.py [--route hika|saya|ori|koro]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
import build_seam as B                                              # noqa: E402

SEAM = ROOT / 'resource' / 'seam-diffs.json'
OUT = ROOT / 'tmp' / 'seams'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--route')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    scripts = [s for s in json.loads(SEAM.read_text(encoding='utf-8'))['scripts']
               if s['needs_rebuild'] and not s['done']]
    if a.route:
        scripts = [s for s in scripts if s['steam'].startswith('yozora_%s_' % a.route)]
    asset, jp = B.load(B.ASSET_RIO), B.load(B.JP_RIO)
    tot = 0
    for s in scripts:
        sc = dict(B.seam_entry(s['steam']), steam=s['steam'], orig=s['orig'])
        _, meta, _, _ = B.build_plan(asset, jp, sc, False, [])
        mixed = [b for b in meta['audit']['blocks'] if b['mixed']]
        keep = [[b['orig_range'][0], b['orig_range'][1]] for b in mixed
                if b['n'][0] != b['n'][1]]
        p = OUT / ('%s.wholeblocks.json' % s['orig'])
        if keep:
            p.write_text(json.dumps(keep, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
            tot += len(keep)
        elif p.exists():
            p.unlink()
        mark = ('整块 %d/%d 块' % (len(keep), len(mixed))) if mixed else '（无候选）'
        print('%-26s %s  %s' % (s['orig'], mark,
                                ' '.join('%s' % k for k in keep) if keep else ''))
    print('\n合计整块还原 %d 块' % tot)


if __name__ == '__main__':
    main()
