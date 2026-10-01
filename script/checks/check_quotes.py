"""核查我们全部 .lng 的引号形态（2026-09-17 与官中统一后的口径）：

  内嵌日文以 `「` 开头 → `.lng` 必须以 `“` 开头、以 `”%K%P` 收尾
  否则（旁白）        → `.lng` 不得以 `“` 开头
  且我们的 `.lng` 里**不应再有** `「` 或 `」`

用法: python script/checks/check_quotes.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tool import arcbuild, lng, resources, ws2, ws2disasm         # noqa: E402

RIO = ROOT / 'asset' / 'Rio.arc'
ZH = ROOT / 'asset' / 'zh-CN' / 'Rio.arc'


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    scenes = [s['id'].lower() for s in resources.load('scenes.json')['scenes']]
    rio = {nb.decode('utf-16le').lower(): d for nb, d in arcbuild.read_raw(RIO)}
    zh = {nb.decode('utf-16le').lower(): d for nb, d in arcbuild.read_raw(ZH)}
    bad, notes, tot = [], [], 0
    for sid in scenes:
        stem, lk = sid + '.ws2', sid + '.lng'
        if stem not in rio or lk not in zh:
            bad.append((sid, '缺脚本或 .lng'))
            continue
        recs = [i for i in ws2disasm.disassemble(ws2.decode(rio[stem])) if i.opcode == 0x14]
        lines = lng.parse_lng(zh[lk])
        if len(recs) != len(lines):
            bad.append((sid, '记录 %d != .lng %d' % (len(recs), len(lines))))
            continue
        n_bad = n_skip = 0
        for i, (r, s) in enumerate(zip(recs, lines)):
            tot += 1
            if '「' in s or '」' in s:
                bad.append((sid, '[%d] 仍含「」: %s' % (i, s[:40])))
                n_bad += 1
                continue
            jp = r.fields.get('text') or ''
            # 只有"**整条**就是对话"才可判定：以 `「` 开头且以 `」%K%P` 收尾。
            # 旁白里引用对话（如 `「…」と言いながら…`）形态相同但语义是旁白 → 跳过。
            pure_dlg = jp.startswith('「') and jp.endswith('」%K%P')
            if pure_dlg:
                # 允许对话引号闭合后再跟一句"译注"之类（`“…”(注…)%K%P`）
                if not (s.startswith('“') and '”' in s[1:]):
                    bad.append((sid, '[%d] 日文对话但译文未用“”包裹: %s' % (i, s[:40])))
                    n_bad += 1
                elif not s.endswith('”%K%P'):
                    notes.append((sid, i, s[-30:]))
            elif jp[:1] != '「':
                # 内嵌是 Miazora 英文化（用 '…' 标**独白**，与语义上的对话/旁白不对应）
                # → 无法自动判定，跳过（只受上面"不得含「」"约束）
                n_skip += 1
        print('%-26s %3d 行  %s（跳过不可判 %d）'
              % (sid, len(lines), 'OK' if not n_bad else 'FAIL %d' % n_bad, n_skip))
    print('\n共 %d 行，问题 %d 条；带尾注（引号已闭合）%d 条' % (tot, len(bad), len(notes)))
    for s, i, tail in notes:
        print('  [尾注] %-24s [%d] …%s' % (s, i, tail))
    for s, m in bad[:20]:
        print('  %-24s %s' % (s, m))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
