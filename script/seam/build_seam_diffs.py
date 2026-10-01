"""构建 `resource/seam-diffs.json`：全部差分接缝的差异总表（唯一数据源）。

差异来自**四个来源**（`doc/file-formats.md` 的「差分接缝修复」；缺一会漏改——试点漏掉第 3 类，实机才发现）：

  1. present_diff   —— 演出指令差异（含"文本相同但演出不同"）
  2. text_record    —— 文本的记录级差异（台词不同 / 原版有·Steam 删 / Steam 新增 / 旁白句数不同）
  3. semantic       —— 同句数无语音句的文本语义改写（前两个工具都看不见）
                       来源：`resource/semantic-rewrites.json`（同句数无语音句的语义改写，带 H/O/K 编号）
  4. resource       —— 资源差异（`resource_diff.py` 的 verdict + isolation 子判定）

用法:
  mamba run -n GalRev python script/seam/build_seam_diffs.py            # 写 resource/seam-diffs.json
  mamba run -n GalRev python script/seam/build_seam_diffs.py --check    # 只做自检与统计，不写文件
"""
import argparse
import difflib
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import present_diff as PD
import seam_profile as SP

SEM_JSON = ROOT / 'resource' / 'semantic-rewrites.json'
RES_CACHE = ROOT / 'tmp' / 'seam_resources'
ABSENT = set()          # 两侧归档都没有、由游戏另处归档提供的资源名（顶层去重输出）


# ---------------------------------------------------------------- 来源 1：演出
def present_items(stem_s, stem_o):
    """[(orig_idx, steam_idx, basis, kind, orig_desc, steam_desc)]"""
    sr, _ = PD.recs('backup', stem_s)
    orr, _ = PD.recs('jp', stem_o)
    sm = difflib.SequenceMatcher(None, [r.voice for r in orr], [r.voice for r in sr], autojunk=False)
    pairs, blocks = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            for k in range(i2 - i1):
                a, b = orr[i1 + k], sr[j1 + k]
                pairs.append((a, b, 'same_anchor' if a.voice else 'unvoiced'))
        else:
            ko, ks = i2 - i1, j2 - j1
            paired = ko == ks and ko > 0
            if paired:
                for k in range(ko):
                    pairs.append((orr[i1 + k], sr[j1 + k], 'in_block'))
            else:
                # 只有**未按位置配对**的块才做块级多重集差异；否则会与逐对结果重复计数
                blocks.append((tag, i1, i2, j1, j2))

    out = []
    for a, b, basis in pairs:
        if a.voice != b.voice:
            out.append((a.idx, b.idx, basis, '语音名不同',
                        ','.join(a.voice) or '（无）', ','.join(b.voice) or '（无）'))
        for kind, x, y in PD.seq_diff(a.keys, b.keys, a.seq, b.seq, a.ins, b.ins):
            out.append((a.idx, b.idx, basis, kind, x, y))
    for tag, i1, i2, j1, j2 in blocks:
        orng = (orr[i1].idx, orr[i2 - 1].idx) if i2 > i1 else None
        srng = (sr[j1].idx, sr[j2 - 1].idx) if j2 > j1 else None
        for desc in PD.block_delta(orr[i1:i2], sr[j1:j2]):
            out.append((orng, srng, 'block', '指令增删', desc, ''))
    return out


# ------------------------------------------------------- 来源 2：文本的记录级
def text_items(stem_s, stem_o):
    """[(label, orig_range, steam_range, 原版句数, Steam 句数, note)]"""
    o, s = SP.walk('jp', stem_o), SP.walk('backup', stem_s)
    uo, us = SP.units(o), SP.units(s)
    ops = difflib.SequenceMatcher(None, [u['voice'] for u in uo],
                                  [u['voice'] for u in us], autojunk=False).get_opcodes()
    out = []
    for tag, i1, i2, j1, j2 in ops:
        if tag == 'equal':
            for k in range(i2 - i1):
                a, b = uo[i1 + k], us[j1 + k]
                if a['narr'] == b['narr']:
                    continue
                alo, ahi = SP.narr_range(o, a)
                blo, bhi = SP.narr_range(s, b)
                out.append(('旁白句数不同', (o[alo]['idx'], o[ahi - 1]['idx']) if ahi > alo else None,
                            (s[blo]['idx'], s[bhi - 1]['idx']) if bhi > blo else None,
                            a['narr'], b['narr'], '位于同一条台词之前'))
            continue
        olo, ohi = SP.span(o, uo, i1, i2)
        slo, shi = SP.span(s, us, j1, j2)
        ocl, ocn = SP.counts(uo, i1, i2)
        scl, scn = SP.counts(us, j1, j2)
        label = {'replace': '台词不同', 'delete': '原版有·Steam 删', 'insert': 'Steam 新增'}[tag]
        out.append((label,
                    (o[olo]['idx'], o[ohi - 1]['idx']) if ohi > olo else None,
                    (s[slo]['idx'], s[shi - 1]['idx']) if shi > slo else None,
                    ocl + ocn, scl + scn,
                    '台词 %d+旁白 %d' % (ocl, ocn) if ohi > olo else '原版无',
                    ))
    return out


# ------------------------------------------- 来源 3：语义改写（读 resource 表）
def semantic_items():
    """{seam_stem: [item]}；来源＝`resource/semantic-rewrites.json`（按新脚本 stem 分组）。"""
    out = {}
    for it in json.loads(SEM_JSON.read_text(encoding='utf-8'))['items']:
        out.setdefault(it['seam'], []).append({
            'label': it['label'], 'position_raw': it.get('position'),
            'orig_jp': it.get('orig_jp'),
            'orig_idx': it.get('orig_idx'), 'steam_idx': it.get('steam_idx'),
        })
    return out


# ------------------------------------------------------------- 来源 4：资源
# 「已完成」= 该接缝的新脚本已登记进 resource/scenes.json（kind = "seam"）。
# 不再硬编码试点，改由表派生 —— 批量重建后 32 个接缝全部为 done。
DONE_SEAMS = {s['id'].lower() for s in
              json.loads((ROOT / 'resource' / 'scenes.json').read_text(encoding='utf-8'))['scenes']
              if s.get('kind') == 'seam'}


def resource_items(stem_s, stem_o):
    RES_CACHE.mkdir(parents=True, exist_ok=True)
    cache = RES_CACHE / ('%s.json' % stem_s)
    if not cache.exists():
        with open(cache, 'w', encoding='utf-8') as fh, open(os.devnull, 'w') as null:
            subprocess.run([sys.executable, str(ROOT / 'script' / 'resource_diff.py'),
                            '--seam', stem_s, stem_o, '--format', 'json'],
                           stdout=fh, stderr=null, cwd=str(ROOT), check=True)
    data = json.loads(cache.read_text(encoding='utf-8'))
    out = []
    for r in data:
        v = r.get('verdict')
        if v in ('SAME',):
            continue
        out.append({
            'name': r.get('name'), 'verdict': v,
            'isolation': r.get('isolation'), 'isolation_name': r.get('isolation_name'),
            'isolation_arc': r.get('isolation_arc'),
        })
    return out


# ------------------------------------------------------------------- 组装
def build():
    ABSENT.clear()
    pairs, seen = [], set()
    for scene, neighbours in SP.SEAMS:
        for role, stem_s, stem_o in neighbours:
            key = (stem_s, stem_o)
            if key in seen:
                continue
            seen.add(key)
            pairs.append((stem_s, stem_o))

    sem = semantic_items()
    scripts = []
    for stem_s, stem_o in pairs:
        pres = present_items(stem_s, stem_o)
        texts = text_items(stem_s, stem_o)
        # 语义条目的键是**新脚本 stem**（无 `_E`），按 orig 匹配
        semis = next((v for k, v in sem.items() if k.upper() == stem_o.upper()), [])
        res = resource_items(stem_s, stem_o)
        rebuild = bool(pres or texts or semis or
                       [r for r in res if r['verdict'] in ('CONFLICT', 'STEAM_MISSING')])
        refs, seen_ref = [], set()
        for r in res:
            if r['verdict'] == 'ABSENT_BOTH':
                ABSENT.add(r['name'])
            if r['name'].upper() not in seen_ref:
                seen_ref.add(r['name'].upper())
                refs.append(r['name'])
        scripts.append({
            'steam': stem_s,
            'orig': stem_o,
            'rebuild_as': stem_o,
            'needs_rebuild': rebuild,
            'done': stem_o.lower() in DONE_SEAMS,
            'counts': {'present': len(pres), 'text': len(texts), 'semantic': len(semis)},
            'present': [dict(zip(('orig_idx', 'steam_idx', 'basis', 'kind', 'orig', 'steam'), p))
                        for p in pres],
            'text': [dict(zip(('kind', 'orig_range', 'steam_range', 'orig_n', 'steam_n', 'note'), t))
                     for t in texts],
            'semantic': semis,
            'resource_refs': refs,
        })

    return {
        '_comment': (
            '全部差分接缝的差异总表。用途：施工单生成（`script/seam/gen_worklist.py`）与复查。'
            '字段：`scripts[]` 按邻居脚本分组（一个 `_E` 脚本可能被两个接缝引用，只出现一次）；'
            '`needs_rebuild=false` 表示该脚本无差异（沿用 Steam）；`done=true` 表示已重建完成'
            '（32 个接缝全部 done，由 `resource/scenes.json` 的 `kind=="seam"` 派生）。'
            '**Steam 侧读 `backup/Rio.arc`**：批量完成后被旁路的 `*_E` 脚本已从 asset 删除。'
            '四类差异：`present`（演出指令）/ `text`（文本记录级）/ `semantic`（同句数无语音句语义改写，'
            '带 H/O/K 来源编号）/ `resource_refs`（**只存资源名**；同名冲突的取舍见 '
            '`resource-decisions.json`，逐脚本的新增部署见 `seam-handling.json`）。'
            '顶层 `absent_both` = 两侧归档都没有、由游戏另处归档提供的资源名。'
            '本文件由 `script/seam/build_seam_diffs.py` 生成，勿手改。'
        ),
        'generated_by': 'script/seam/build_seam_diffs.py',
        'absent_both': sorted(ABSENT),
        'scripts': scripts,
    }


def selfcheck(table):
    print('%-34s %-6s %s' % ('脚本', '需重建', 'present/text/semantic'))
    tot = Counter()
    for s in table['scripts']:
        c = s['counts']
        flag = 'YES' if s['needs_rebuild'] else 'no '
        if s['done']:
            flag = 'DONE'
        print('%-34s %-6s %d / %d / %d' % (
            s['steam'], flag, c['present'], c['text'], c['semantic']))
        for k, v in c.items():
            tot[k] += v
    print('\n合计: 脚本 %d（需重建 %d，已完成 %d）; present %d / text %d / semantic %d；'
          'absent_both %d' % (
              len(table['scripts']),
              sum(1 for s in table['scripts'] if s['needs_rebuild']),
              sum(1 for s in table['scripts'] if s['done']),
              tot['present'], tot['text'], tot['semantic'], len(table['absent_both'])))

    # 关键自检：103e 必须带上 semantic 的 H1/H2（idx 1/2/17）
    e = [s for s in table['scripts'] if s['steam'] == 'yozora_hika_103e_E']
    print('\n[自检] 103e 的 semantic 条目:')
    for it in (e[0]['semantic'] if e else []):
        print('   %s idx %s' % (it['label'], it['orig_idx']))
    # 语义条目落在 present/text 区间内 → overlap（那块本来就会被替换）
    print('\n[自检] 语义条目与文本块的关系:')
    for s in table['scripts']:
        for it in s['semantic']:
            if not it['orig_idx']:
                continue
            lo, hi = it['orig_idx']
            hit = [t for t in s['text'] if t['orig_range'] and
                   not (t['orig_range'][1] < lo or hi < t['orig_range'][0])]
            print('   %-32s %-3s idx %s  %s' % (
                s['steam'], it['label'], it['orig_idx'],
                '在文本差异块内（%s）' % hit[0]['kind'] if hit else '★ 落在"相同"区间（隐形类，必须单列）'))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true')
    a = ap.parse_args()
    t = build()
    selfcheck(t)
    if not a.check:
        out = ROOT / 'resource' / 'seam-diffs.json'
        out.write_text(json.dumps(t, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        print('\n已写出 %s（%d 脚本）' % (out, len(t['scripts'])))
