"""收集 31 个待重建接缝的原版脚本用到的 `%LF` 说话人前缀，推导其官中映射。

输出 tmp/seams/_nametable.json（`--nametable-json` 的输入）：`{"%LF日文名": "%LF中文名"}`。
映射来源：`asset/zh-CN/Rio.arc` 的 `NameTable.txt`（键为**英文名**）+ 日文名→英文名的对照。
未能映射的会列出来要求人工补。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
import build_seam as B                                              # noqa: E402
from tool import arcbuild, lng, ws2, ws2disasm                       # noqa: E402

SEAM = ROOT / 'resource' / 'seam-diffs.json'
OUT = ROOT / 'tmp' / 'seams'
JP2EN = {'ひかり': 'Hikari', '暁斗': 'Akito', '沙夜': 'Saya', '織姫': 'Orihime',
         'ころな': 'Korona', '美晴': 'Miharu', '田尻': 'Keisuke', 'あまこ': 'Amako'}
# 配角：JP 名 → 官中值（键为罗马字，已逐条对照 NameTable 的键与值确认）
JP2CN = {
    'いっしー': '%LF小一',              # Isshy
    'まりも': '%LF真理美',              # Marimo
    'コタロウ': '%LF虎太郎',             # Kotarou
    'タケムラ': '%LF武村',              # Takemura
    '一同': '%LF众人',                # Everyone
    '吉岡': '%LF吉冈',                # Honoka
    '川中島': '%LF川中岛',              # Kawanakajima
    '店長': '%LF店长',                # Store Manager
    '武一': '%LF武一',                # Takeichi
    '田尻': '%LF田尻',                # Keisuke
    '豊田': '%LF丰田',                # Toyoda
    '部長': '%LF社长',                # President
    '陣野': '%LF阵野',                # Narue
    '陽南': '%LF阳南',                # Hinami
    'ＡＫＩＴＯ': '%LF晓斗',             # Akito（全角）
    '明光の女子生徒': '%LF明光的女学生',      # Female Meikou Student
    '諸見沢工業の天文部員': '%LF诸美泽工业的天文社团成员',  # Moromisawa Astronomy Club Member
    'まさよし＠西ノ宮': '%LF正吉＠西之宫',     # Masayoshi\aNishinomiya
    'ガッちん＠赤石': '%LF正直富有正义感＠赤石',  # Gatchin\aAkashi
    'ルミカ＠姫森': '%LF露米嘉＠姬森',      # Rumika\aHimemori
    '百花＠恵風': '%LF百花@惠风',         # Momoka\aKeifuu
    '吉岡＠むつらぼし': '%LF吉冈@六连星',     # Honoka\a6 Stars
}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    zh = {nb.decode('utf-16le'): d for nb, d in arcbuild.read_raw(B.ZH_RIO)}
    nt = zh['NameTable.txt'].decode('utf-16le')
    eng2cn = {}
    for ln in nt.split('\r\n'):
        if '\t' in ln:
            k, v = ln.split('\t', 1)
            eng2cn[k.strip()] = v.strip()
    scripts = [s for s in json.loads(SEAM.read_text(encoding='utf-8'))['scripts']
               if s['needs_rebuild'] and not s['done']]
    jp = B.load(B.JP_RIO)
    need = {}
    for s in scripts:
        _, raw = B.find(jp, s['orig'])
        for i in ws2disasm.disassemble(ws2.decode(raw)):
            if i.opcode == 0x15:
                p = i.fields.get('prefix') or ''
                if p.startswith('%LF'):
                    need.setdefault(p, set()).add(s['orig'])
    out, unknown = {}, []
    # 1) 直接按 JP→EN→CN 或 JP→CN（配角）映射
    for p in sorted(need):
        name = p[len('%LF'):]
        if name in JP2CN:
            out[p] = JP2CN[name]
            continue
        if name in JP2EN:
            e = '%LF' + JP2EN[name]
            if e in eng2cn:
                out[p] = eng2cn[e]
    # 2) 对未映射的：找一条**已配对**的记录，读它 Steam 侧的前缀（英文）再查表
    asset = B.load(B.ASSET_RIO)
    for s in scripts:
        sc = dict(B.seam_entry(s['steam']), steam=s['steam'], orig=s['orig'])
        _, meta, _, (S, O) = B.build_plan(asset, jp, sc, False, [])
        _, recs_o, _ = B.segment(O)
        _, recs_s, _ = B.segment(S)
        o2s = meta['o2s']
        for oi, rec in enumerate(recs_o):
            pref = next((i.fields.get('prefix') for i in rec if i.opcode == 0x15), None)
            if not pref or not pref.startswith('%LF') or pref in out or pref not in need:
                continue
            si = o2s.get(oi)
            if si is None or si >= len(recs_s):
                continue
            sp = next((i.fields.get('prefix') for i in recs_s[si] if i.opcode == 0x15), None)
            if sp and sp in eng2cn:
                out[pref] = eng2cn[sp]
    for p in sorted(need):
        if p not in out:
            unknown.append((p, sorted(need[p])[:3]))
    (OUT / '_nametable.json').write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n',
                                         encoding='utf-8')
    print('需要 %d 种前缀，已映射 %d：' % (len(need), len(out)))
    for k, v in out.items():
        print('   %-14s → %-14s  用于 %d 场景' % (k, v, len(need[k])))
    print('\n未映射 %d（需人工给中文名）：' % len(unknown))
    for p, sc in unknown:
        print('   %-16s 用于 %s' % (p, sc))
    if not unknown:
        print('   （无）')


if __name__ == '__main__':
    main()
