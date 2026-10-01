"""为一个差分接缝生成**固定的**译文本施工单（避免施工单遗漏）。

输出（默认 `tmp/seams/`）：
  <orig>.translations.json  译文模板 `{idx: ""}`（**已存在则不覆盖**，保护译者已填内容）
  <orig>.worklist.md        逐条待译清单：原版日文内嵌文本 + Steam 侧对应句（语境）+ 引号形态
  <orig>.rename.json        `--rename-json` 输入：本场景引用到的**真冲突**资源的改名表
  <orig>.wholeblocks.json   `--whole-blocks` 候选（"同时含还原与保留"的 text 块，需人核）

用法:
  python script/seam/pin_translations.py --steam yozora_hika_103c_E --orig yozora_hika_103c
  [--out-dir tmp/seams] [--decisions tmp/resource_decisions.json] [--force]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
import build_seam as B                                            # noqa: E402
from tool import ws2, ws2disasm                                   # noqa: E402

TEXT = 0x14


def refs_of(members, stem):
    """该脚本引用的全部资源名（各指令操作数的原始字节）。"""
    out = []
    _, raw = B.find(members, stem)
    for i in ws2disasm.disassemble(ws2.decode(raw)):
        out.append(i.operands)
    return out


def find_spelling(refs, name):
    """在脚本操作数里找出 name 的实际拼写（返回字节），用于对齐大小写惯例。"""
    nb = name.encode('shift_jis')
    for r in refs:
        i = r.upper().find(nb.upper())
        if i >= 0:
            return r[i:i + len(nb)]
    return None


def match_ext(iso, spelling):
    """把隔离名的扩展名（`.PNA`/`.pna`）改成脚本里的实际写法。"""
    if not spelling or b'.' not in spelling or '.' not in iso:
        return iso
    ext = spelling.rsplit(b'.', 1)[1].decode('ascii', 'ignore')
    return iso.rsplit('.', 1)[0] + '.' + ext


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--steam', required=True)
    ap.add_argument('--orig', required=True)
    ap.add_argument('--out-dir', default=str(ROOT / 'tmp' / 'seams'))
    ap.add_argument('--decisions', default=str(ROOT / 'resource' / 'resource-decisions.json'))
    ap.add_argument('--whole-blocks', help='JSON [[lo,hi],...]：整块取原版的记录区间'
                                           '（先用本工具输出的 `.wholeblocks.json` 候选人工确认）')
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')

    outdir = Path(a.out_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    sc = dict(B.seam_entry(a.steam), steam=a.steam, orig=a.orig)
    asset, jp = B.load(B.ASSET_RIO), B.load(B.JP_RIO)
    wb = ([(r[0], r[1]) for r in json.loads(Path(a.whole_blocks).read_text(encoding='utf-8'))]
          if a.whole_blocks else [])
    plan, meta, _, (S, O) = B.build_plan(asset, jp, sc, False, wb)
    o2s = meta['o2s']
    _, recs_o, _ = B.segment(O)
    _, recs_s, _ = B.segment(S)
    restore = sorted(meta['restore'])

    # ---- 译文本模板 -------------------------------------------------------
    tj = outdir / ('%s.translations.json' % a.orig)
    if tj.exists() and not a.force:
        print('保留既有 %s（%d 条）' % (tj, len(json.loads(tj.read_text(encoding='utf-8')))))
    else:
        tj.write_text(json.dumps({str(i): '' for i in restore}, ensure_ascii=False, indent=1)
                      + '\n', encoding='utf-8')
        print('已写出 %s（%d 条待译）' % (tj, len(restore)))

    # ---- 改名表 -----------------------------------------------------------
    dec = {}
    dp = Path(a.decisions)
    if dp.exists():
        dec = json.loads(dp.read_text(encoding='utf-8'))
    refs = refs_of(asset, a.steam) + refs_of(jp, a.orig)
    rename, pending = {}, []
    for name, v in dec.items():
        if name.startswith('_'):
            continue
        sp = find_spelling(refs, name)
        if sp is None:
            continue
        if v['verdict'] == '真冲突':
            if v.get('isolation_name'):
                rename[name] = match_ext(v['isolation_name'], sp)
            else:
                pending.append((name, '真冲突但隔离名未定'))
        elif v['verdict'] == '待定':
            pending.append((name, '待定（需人工裁定）'))
    rj = outdir / ('%s.rename.json' % a.orig)
    rj.write_text(json.dumps({'_comment': '仅真冲突资源改名（由 pin_translations 从 decisions 筛出）',
                              **rename}, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print('已写出 %s（%d 项改名）' % (rj, len(rename)))

    # ---- 整块候选（只提示，不自动应用）------------------------------------
    mixed = [b for b in meta['audit']['blocks'] if b['mixed']]
    cand = outdir / ('%s.wholeblocks.candidates.json' % a.orig)
    cand.write_text(json.dumps([[b['orig_range'][0], b['orig_range'][1]] for b in mixed],
                               ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    wb_path = outdir / ('%s.wholeblocks.json' % a.orig)
    if a.whole_blocks:
        import shutil as _sh
        if Path(a.whole_blocks).resolve() != wb_path.resolve():
            _sh.copyfile(a.whole_blocks, wb_path)
        print('已应用整块 %s → %s' % (a.whole_blocks, wb_path))
    elif mixed:
        print('!! 存在 %d 个"同时含还原与保留"的 text 块（见 %s）——本单**未应用**；'
              '人工确认后重跑并传 --whole-blocks，否则译文条数会与构建器不一致'
              % (len(mixed), cand.name))
        if wb_path.exists():
            wb_path.unlink()
    print('已写出 %s（%d 个整块候选）' % (cand, len(mixed)))

    # ---- 施工单 markdown --------------------------------------------------
    md = ['# 接缝施工单：`%s`（基底 Steam `%s`）\n' % (a.orig, a.steam),
          '> 由 `script/seam/pin_translations.py` 生成（**不要手改**）。'
          '差异四来源：演出 present / 文本记录级 text / 同句数无语音句 semantic / 资源 resource。\n',
          '- 原版记录 %d；Steam 记录 %d；**共用 %d / 差分类 %d**'
          '（未配对 %d ∪ 语义 %d ∪ 整块 %d）'
          % (meta['n_o'], meta['n_s'], meta['n_o'] - len(restore), len(restore),
             len(meta['audit']['unpaired']), len(meta['audit']['semantic_records']),
             len(meta['audit']['whole_blocks'])),
          '- 译文模板：`%s`；改名表：`%s`%s' % (
              tj.name, rj.name,
              ('；整块：`%s`' % wb_path.name) if a.whole_blocks else ''), '']
    if mixed and not a.whole_blocks:
        md += ['', '> ⚠ **整块未应用**：见 `%s`（%d 块）。确认后重跑：'
               '`--whole-blocks <确认后的 json>`，否则译文条数少于构建器所需。'
               % (cand.name, len(mixed))]
    if pending:
        md += ['## ⚠ 需用户裁定（执行前必须上报）', '']
        for n, why in pending:
            md += ['- 资源 `%s`：%s' % (n, why)]
        md += ['']
    if mixed:
        md += ['## ⚠ "同时含还原与保留" 的 text 块（`--whole-blocks` 候选，需人核）', '']
        for b in mixed:
            md += ['- %s orig=%s steam=%s n=%s：还原 %s / 保留 %s'
                   % (b['kind'], b['orig_range'], b['steam_range'], b['n'],
                      b['restored'], b['kept'])]
        md += ['']
    md += ['## 待译清单（%d 条，**逐条必填**）\n' % len(restore), '']
    md += ['| idx | 原版日文（内嵌，含控制符） | 对应 Steam 句（语境） | 引号 |',
           '|---|---|---|---|']
    for oi in restore:
        jp = recs_o[oi][-1].fields.get('text') or ''
        si = o2s.get(oi)
        st = (recs_s[si][-1].fields.get('text') or '') if si is not None else '（Steam 无对应）'
        q = '对话「」' if jp.startswith('「') else '旁白（不加引号）'
        md += ['| %d | `%s` | `%s` | %s |'
               % (oi, jp.replace('|', '\\|'), st.replace('|', '\\|')[:60], q)]
    wb_arg = ('--whole-blocks %s ' % wb_path) if a.whole_blocks else ''
    vline = ('  --steam %s --orig %s --translations %s --rename-json %s %s'
             % (a.steam, a.orig, tj, rj, wb_arg)).rstrip()
    md += ['', '## 执行', '',
           '```bash', 'mamba run -n GalRev python script/seam/build_seam.py \\',
           '  --steam %s --orig %s \\' % (a.steam, a.orig),
           '  --translations %s --rename-json %s \\' % (tj, rj),
           '  %s--dry    # 先 dry，核对后再去掉 --dry' % wb_arg,
           'mamba run -n GalRev python script/seam/verify_seam.py \\',
           vline,
           '```']
    wp = outdir / ('%s.worklist.md' % a.orig)
    wp.write_text('\n'.join(md) + '\n', encoding='utf-8')
    print('已写出 %s（待译 %d 条；⚠ %d 项待裁定；整块候选 %d）'
          % (wp, len(restore), len(pending), len(mixed)))


if __name__ == '__main__':
    main()
