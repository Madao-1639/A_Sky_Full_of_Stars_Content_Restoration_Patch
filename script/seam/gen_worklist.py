"""从 `resource/seam-diffs.json` 生成**单个接缝的施工单**（markdown）。

四类差异（演出 / 文本记录级 / 同句数无语音句语义 / 资源）全部来自数据表，不手工维护——
试点曾因施工单只覆盖 `present`+`text` 两类、漏掉 `semantic` 一类（实机才发现"一百个吻的余韵"）。

用法:
  python script/seam/gen_worklist.py yozora_hika_103e_E            # 打印到 stdout
  python script/seam/gen_worklist.py yozora_hika_103e_E -o /tmp/x.md
  python script/seam/gen_worklist.py --list                        # 列出所有接缝与其差异规模
  python script/seam/gen_worklist.py --sample saya                 # 抽一条该路线的脚本
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tool import ws2patch

TABLE = ROOT / 'resource' / 'seam-diffs.json'
DEC_TABLE = ROOT / 'resource' / 'resource-decisions.json'

# 同名冲突的最终取舍（`seam-diffs.json` 只存资源名，判定一律查这张表）
_DEC = {k.upper(): v for k, v in
        json.loads(DEC_TABLE.read_text(encoding='utf-8')).items() if not k.startswith('_')}


def decision_of(name):
    return _DEC.get((name or '').upper(), {})
KIND_VOICE = '语音名不同'
KIND_RES = '资源名不同'
KIND_PARAM = '演出参数不同'
KIND_ADD = '指令增删'

# ---- 指令分类表（判据：是否与演出相关）→ 决定每条差异用原版还是 Steam
POLICY, _BY_OP, _OPS_RAW = ws2patch.load_present_ops()
KEEP_STEAM = [o for o in _OPS_RAW if o['policy'] == 'keep_steam' and o['in_diffs'] > 0]


def policy_of(desc, kind):
    """(policy, opcode) —— 从差异描述里取 opcode 名再查表。"""
    if kind == KIND_VOICE:
        return 'use_orig', '0x2e'
    s = desc or ''
    for pre in ('Steam 独有：', '原版独有：'):
        if s.startswith(pre):
            s = s[len(pre):]
    tok = (s.split() or [''])[0].lower()
    o = POLICY.get(tok)
    return (o['policy'], o['opcode']) if o else (None, None)

# 引用扫描已并入 tool/ws2patch（build_seam 经 `import gen_worklist` 取用，保持同名导出）
callers_of = ws2patch.callers_of


def file_of(desc):
    m = re.search(r'file=(\S+)', desc or '')
    return m.group(1) if m else None


def slash(desc):
    """'UsePnaPackage slot=st01 file=Aひかり_03L.PNA flags=0101' → 'Aひかり_03L.PNA'"""
    f = file_of(desc)
    return f or (desc or '').strip() or '（空）'


def acts(sc):
    """给每条差异定 action。判据 = `resource/present-ops.json` 的"是否与演出相关"；
    生成器不替用户判断演出：判不了的一律 needs_user 并进 ⚠ 段。"""
    out = []
    for p in sc['present']:
        kind, basis = p['kind'], p['basis']
        if kind == KIND_ADD and basis == 'block':
            # 块级差异是聚合描述（非单一 opcode）→ 整块取原版
            act, note, op = 'use_orig', '整块（未逐句配对）→ 该块演出整体取原版', None
        else:
            pol, op = policy_of(p.get('orig'), kind)
            if pol is None:
                pol, op = policy_of(p.get('steam'), kind)
            if pol is None:
                act, note = 'needs_user', '描述里取不到 opcode，需人工判断'
            elif pol == 'needs_user':
                act, note = 'needs_user', 'opcode %s 的演出归属未定（见 present-ops.json）' % op
            elif pol == 'keep_steam':
                act, note = 'keep_steam', 'opcode %s 与演出无关 → 保留 Steam（不动）' % op
            elif kind == KIND_ADD:
                side = '原版' if (p['orig'] or '').startswith('原版') else 'Steam'
                act = 'insert_orig' if side == '原版' else 'delete_steam'
                note = side + '独有指令（演出相关 → 取原版）'
            elif kind == KIND_VOICE:
                act, note = 'use_orig', '换回原版 OGG'
            else:
                act, note = 'use_orig', '演出参数/资源按原版'
        out.append({**p, 'action': act, 'note': note, 'op': op})
    return out


def render(sc, out):
    P = out.append
    w = P
    items = acts(sc)
    user_needed = [i for i in items if i['action'] == 'needs_user']
    P('# 施工单：新建 `%s`（基底 Steam `%s`，演出整套回原版）\n' % (sc['rebuild_as'], sc['steam']))
    P('> 由 `script/seam/gen_worklist.py` 从 `resource/seam-diffs.json` 生成（**不要手改本文件**）。')
    P('> 依据：`doc/file-formats.md` 的「差分接缝修复」；差异四类来源＝演出 / 文本记录级 / 同句数无语音句语义 / 资源。\n')
    if user_needed:
        P('## ⚠ 需用户裁定（执行前必须上报，不得自行决定）\n')
        grp = defaultdict(list)
        for i in user_needed:
            grp[i.get('op') or 'undefined'].append(i)
        for op, rows in sorted(grp.items()):
            P('- **`%s`** ×%d 处（策略 `needs_user`，见 `resource/present-ops.json`）'
              % (op, sum(1 for r in rows if r.get('kind'))))
            for i in rows[:3]:
                if not i.get('kind'):
                    continue
                P('  - idx 原版 %s ⇄ Steam %s：原版侧 `%s` ⇄ Steam 侧 `%s`'
                  % (i.get('orig_idx'), i.get('steam_idx'),
                     i.get('orig') or '（无）', i.get('steam') or '（无）'))
        P('')
    P('## 0. 基底与保留项\n')
    P('- **基底** = `asset/Rio.arc` 的 `%s` 的原始字节（rot6）' % sc['steam'])
    P('- **保留不动（与演出无关 → 用 Steam 版）**：' +
      '、'.join('`%s %s`' % (o['opcode'], o['name']) for o in KEEP_STEAM))
    P('  - 其中含：跳过已读机制（`GetMsgSkip`/`Condition`/`0x02 Jump2`）、`0x11 SetTimer` 的 Steam 编码形态、'
      '`0x0b SetFlag`（承载 gallery/成就 id）、`0x16`（图层块/对话框层）、前导/尾部结构、`0xff` 沿用 Steam 原值')
    P('- **判不了的 opcode**（`needs_user`）见本单顶部 ⚠ 段，**执行前必须上报**')
    P('- **说话人前缀**：差分块/补回句用**原版日文名**；共用块保持 Steam 的英文前缀（扩 NameTable 后都命中）')
    P('- 条数最终 = **原版句数**（撤销 Steam 的增删）；idx 重排 `0..N-1`')
    P('- **资源名一律按 §5 的隔离判定**：凡 §1–§4 里出现 §5 中标为 `CONFLICT` 的裸名资源，'
      '**改用其隔离名**（`HANDLED` → 引用已有隔离名；`NEEDS_ISOLATION` → 补入原版后用隔离名），'
      '不要照抄原版脚本里的裸名\n')

    voice = [i for i in items if i['kind'] == KIND_VOICE]
    P('## 1. 语音名（%d 处，换回原版 OGG）\n' % len(voice))
    if voice:
        P('| 原版 idx | Steam idx | 原版 | Steam | 位置 |')
        P('|---|---|---|---|---|')
        for i in voice:
            P('| %s | %s | %s | %s | %s |' % (i['orig_idx'], i['steam_idx'],
                                              i['orig'], i['steam'], i['basis']))
    else:
        P('（无）')
    P('')

    pres = [i for i in items if i['kind'] in (KIND_RES, KIND_PARAM) and i['basis'] != 'block']
    P('## 2. 演出差异（%d 处，按是否与演出相关取原版/Steam）\n' % len(pres))
    if pres:
        P('| 原版 idx | Steam idx | 类别 | 原版 | Steam | 处理 |')
        P('|---|---|---|---|---|---|')
        for i in pres:
            iso = ''
            if i['kind'] == KIND_RES:
                o = slash(i['orig'])
                d = decision_of(o)
                if d.get('verdict') == '真冲突' and d.get('isolation_name'):
                    iso = '；改隔离名 `%s`' % d['isolation_name']
            base = {'use_orig': '取原版', 'keep_steam': '保留 Steam（不动）',
                    'needs_user': '**需裁定**'}.get(i['action'], i['action'])
            P('| %s | %s | %s | %s | %s | %s%s |' % (i['orig_idx'], i['steam_idx'], i['kind'],
                                                     i['orig'], i['steam'], base, iso))
    else:
        P('（无）')
    P('')

    blocks = [i for i in items if i['kind'] == KIND_ADD and i['basis'] == 'block']
    adds = [i for i in items if i['kind'] == KIND_ADD and i['basis'] != 'block']
    n_block = len({(str(i['orig_idx']), str(i['steam_idx'])) for i in blocks})
    P('## 3. 指令增删（逐句 %d 处；另有 %d 个未配对块、共 %d 条块级差异）\n'
      % (len(adds), n_block, len(blocks)))
    if blocks:
        P('**未逐句配对的差异块 → 整块演出取原版**（块级差异逐条列出，便于对账）\n')
        for i in blocks:
            P('- 原版 idx %s ⇄ Steam idx %s：%s' % (i['orig_idx'], i['steam_idx'], i['orig']))
        P('')
    ACT_ZH = {'use_orig': '取原版', 'keep_steam': '保留 Steam（不动）',
              'needs_user': '**需裁定**', 'insert_orig': '补回原版该指令',
              'delete_steam': '删掉 Steam 多出的该指令'}
    if adds:
        P('| 原版 idx | Steam idx | 类别 | 内容 | 处理 |')
        P('|---|---|---|---|---|')
        for i in adds:
            P('| %s | %s | %s | %s | %s |' % (i['orig_idx'], i['steam_idx'], i['kind'],
                                              i['orig'] or i['steam'],
                                              ACT_ZH.get(i['action'], i['action'])))
    else:
        P('（无）')
    P('')

    P('## 4. 文本（记录级差异 + **同句数无语音句语义改写**）\n')
    P('### 4a. 记录级差异（%d 块）\n' % len(sc['text']))
    if sc['text']:
        P('| 类别 | 原版 idx | Steam idx | 原版句数 | Steam 句数 | 处理 |')
        P('|---|---|---|---|---|---|')
        for t in sc['text']:
            P('| %s | %s | %s | %s | %s | 整块取原版 / 按原版补回 / 删 Steam 多出 |'
              % (t['kind'], t['orig_range'] or '—', t['steam_range'] or '—', t['orig_n'], t['steam_n']))
    else:
        P('（无）')
    P('')
    P('### 4b. 同句数无语音句语义改写（%d 处）★ 前两个工具都看不见，**必须逐条执行**\n' % len(sc['semantic']))
    if sc['semantic']:
        P('| 来源 | 原版 idx | Steam idx | 位置原文 | 原版日文 | 处理 |')
        P('|---|---|---|---|---|---|')
        for s in sc['semantic']:
            P('| %s | %s | %s | %s | %s | 取原版 + 新译进 `.lng` |'
              % (s['label'], s['orig_idx'], s['steam_idx'], s['position_raw'], s['orig_jp']))
    else:
        P('（无）')
    P('')

    refs = sc.get('resource_refs', [])
    P('## 5. 资源（%d 项）\n' % len(refs))
    if refs:
        P('| 资源 | 同名冲突取舍 | 隔离名 | 处理 |')
        P('|---|---|---|---|')
        for name in refs:
            d = decision_of(name)
            v = d.get('verdict') or '—'
            # 隔离名只在"真冲突"下才是本单该引用的名；其它档位（误报等）不应显示
            iso = d.get('isolation_name') if v == '真冲突' else None
            if v == '真冲突':
                act = '引用隔离名（原版另行部署）'
            elif v in ('误报', '本地化', '采用Steam'):
                act = '直接用 Steam 裸名'
            elif v == '待定':
                act = '**需人工核**'
            else:
                act = '非同名冲突：Steam 缺失则按 `seam-handling.json` 的 `resources_added`；'\
                      '两侧都没有则由游戏另处归档提供'
            P('| %s | %s | %s | %s |' % (name, v, d.get('isolation_name') or '—', act))
    else:
        P('（无）')
    P('')

    P('## 6. 偏移重定位（长度变化后必做）\n')
    P('- `0x02 Jump2` / `0x06 Jump` 的操作数是**文件内绝对偏移** → 按 old→new 映射重写 target')
    P('- `EVRET` field1/field2 同类（`_H` 场景才有）；项目已有 `script/tools/fix_evret_offsets.py`')
    P('- 重定位后**回读校验**每条跳转指向的指令边界\n')

    P('## 7. `.lng` 与 `NameTable`\n')
    P('- 新建 `asset/zh-CN/Rio.arc` 的 `%s.lng`：条数 = **原版句数**，与脚本文本记录逐条同序' % sc['rebuild_as'])
    P('  - 共用句：取 `%s.lng` 对应内容的中文（按内容对齐映射，不是按 idx 硬搬）' % sc['steam'])
    P('  - 差分句（§1/§2/§4 涉及的）：**新译**（输入为原版日文，结合语境）')
    P('  - **角色对话一律用 `「」` 包裹**；旁白不加引号；旁白内部强调沿用 `“”`；每条以 `%K%P` 收尾')
    P('  - 编码走 `tool/lng.encode_lng()`；长度表自洽校验')
    P('- `NameTable.txt` **按需追加**本脚本用到的原版日文名（既有条目不动）\n')

    P('## 8. 写入与跳转\n')
    P('- `asset/Rio.arc`：**新增**成员 `%s.ws2`（大小写按归档惯例；追加到末尾）' % sc['rebuild_as'])
    P('- `asset/zh-CN/Rio.arc`：新增 `.lng`、按需追加 NameTable 条目')
    cs = callers_of(sc['steam'])
    P('- **跳转改写**：指向 `%s` 的脚本需改指 `%s`：' % (sc['steam'], sc['rebuild_as']))
    for c in (cs or ['（无引用者；需人工确认是否已是死脚本）']):
        P('  - `%s`' % c)
    P('- **不要删除** `%s`（等实机验证通过）\n' % sc['steam'])

    P('## 9. 验证（必须逐项）\n')
    P('- **强不变式①**：差分类记录的**演出指令** == 原版')
    P('- **强不变式②**：差分类记录的**内嵌文本** == 原版')
    P('- **强不变式③**：`.lng` 引号形态（对话 `「…」%K%P`、旁白无引号、字面 `\\n` 个数与原版一致）')
    P('- `disassemble` 100% tile；条数 = 原版句数；idx 连续')
    P('- 跳转 target 重定位正确；`arcbuild.verify` 通过；回读成员 SHA')
    P('- `script/checks/verify_ws2_disasm.py`、`script/final_verification.py` 通过；构建器幂等')
    P('- **不要删除**被旁路的 `_E` 脚本')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('steam', nargs='?')
    ap.add_argument('-o', '--out')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--sample')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')

    table = json.loads(TABLE.read_text(encoding='utf-8'))
    scripts = {s['steam']: s for s in table['scripts']}

    if a.list:
        for s in table['scripts']:
            c = s['counts']
            print('%-34s rebuild=%-5s done=%-5s present=%-4d text=%-2d semantic=%-2d res_refs=%d'
                  % (s['steam'], s['needs_rebuild'], s['done'], c['present'], c['text'],
                     c['semantic'], len(s.get('resource_refs', []))))
        return

    stem = a.steam
    if a.sample:
        cand = [s['steam'] for s in table['scripts']
                if s['needs_rebuild'] and not s['done'] and a.sample in s['steam']]
        if not cand:
            raise SystemExit('该路线没有待重建脚本')
        stem = cand[0]
        print('# 抽样：%s\n' % stem, file=sys.stderr)
    if not stem:
        raise SystemExit('需要 <steam_stem> 或 --list/--sample')

    sc = scripts.get(stem)
    if sc is None:
        raise SystemExit('表中没有 %s' % stem)

    out = []
    render(sc, out)
    text = '\n'.join(out) + '\n'
    if a.out:
        Path(a.out).write_text(text, encoding='utf-8')
        print('已写出 %s' % a.out)
    else:
        sys.stdout.write(text)


if __name__ == '__main__':
    main()
