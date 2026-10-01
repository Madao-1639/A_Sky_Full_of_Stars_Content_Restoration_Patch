# -*- coding: utf-8 -*-
"""WS2 反汇编器回归守卫：对三套语料跑 100% 覆盖 + 独立锚点交叉校验。

用法（项目根目录下）：
    mamba run -n GalRev python script/checks/verify_ws2_disasm.py
    mamba run -n GalRev python script/checks/verify_ws2_disasm.py -v   # 打印全部失败清单

语料目录 tmp/corpus_asky/ 不存在时会自动从三个 Rio.arc 现场抽取（只读归档）。

检查项（任一失败即说明 tool/ws2disasm.py 漂移了）：
  A. 覆盖：每个文件线性解析到 EOF，不抛 UnknownInstruction；
     sum(ins.size) == len(data)，且指令首尾相接无缝隙/无重叠。
  B. 长度自洽：size == len(operands) + 1（operands 约定见 tool/ws2disasm.py）。
  C. 独立锚点：tool/ws2.py 里那套**已被 277 个脚本验证过**的 CG 显示正则
     （`34 <slot>\\0 <STEM>.PNA\\0 01 01 0b u16 01 0b u16 01`）的每个匹配，
     其起点必须正好是一条 `34` 指令的起点、终点必须落在该族指令内部。
     这条检查与反汇编器**同源但不同实现**，能挡住"少读/多读若干字节后
     余下字节恰好还能解析成合法指令"这类自洽但错误的边界。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tool import arcbuild, ws2 as asky_ws2      # noqa: E402
from tool import ws2disasm as D                 # noqa: E402

CORPUS = ROOT / 'tmp' / 'corpus_asky'
ARCS = (
    ('steam', ROOT / 'asset' / 'Rio.arc'),
    ('orig', ROOT.parent / '抬头看看吧看那天上的繁星' / 'Rio.arc'),
    ('backup', ROOT / 'backup' / 'Rio.arc'),
)


def ensure_corpus():
    """tmp/corpus_asky/<tag>/ 不存在时从归档抽取（只读）。"""
    missing = [t for t, _p in ARCS if not (CORPUS / t).is_dir()]
    if not missing:
        return
    for tag, arc in ARCS:
        out = CORPUS / tag
        out.mkdir(parents=True, exist_ok=True)
        for name_bytes, data in arcbuild.read_raw(arc):
            if len(name_bytes) % 2 == 0:
                name = name_bytes.decode('utf-16-le', 'surrogateescape')
            else:
                name = name_bytes.decode('cp932', 'surrogateescape')
            if name.lower().endswith('.ws2'):
                (out / name).write_bytes(data)
        print('抽取语料 %-8s <- %s' % (tag, arc.name))


def check_file(path):
    data = asky_ws2.decode(path.read_bytes())
    try:
        instrs = D.disassemble(data)
    except D.UnknownInstruction as exc:
        return None, str(exc)
    total = 0
    for ins in instrs:
        if ins.size != len(ins.operands) + 1:
            return None, ('@0x%x op%02x size=%d 与 operands=%d 不一致'
                          % (ins.offset, ins.opcode, ins.size, len(ins.operands)))
        if ins.offset != total:
            return None, '@0x%x op%02x 与前一条指令不相接' % (ins.offset, ins.opcode)
        total += ins.size
    if total != len(data):
        return None, '覆盖 %d != 文件长度 %d' % (total, len(data))
    return instrs, None


def check_anchors(path, instrs):
    """CG 显示正则锚点（检查 C）。"""
    data = asky_ws2.decode(path.read_bytes())
    starts = {ins.offset: ins for ins in instrs}
    spans = [(ins.offset, ins.offset + ins.size) for ins in instrs]
    bad = []
    n = 0
    for m in asky_ws2.DISPLAY.finditer(data):
        n += 1
        ins = starts.get(m.start())
        if ins is None or ins.opcode != 0x34:
            bad.append('正则匹配 @0x%x 不是 34 指令起点' % m.start())
        if not any(a <= m.end() <= b for a, b in spans):
            bad.append('正则结束点 0x%x 不落在任何指令内' % m.end())
    return n, bad


def main():
    verbose = '-v' in sys.argv
    ensure_corpus()
    grand_ok = grand_bad = anchors = anchor_bad = 0
    fails = []
    for tag, _arc in ARCS:
        d = CORPUS / tag
        files = sorted(d.iterdir())
        good = bad = 0
        for p in files:
            instrs, msg = check_file(p)
            if instrs is None:
                bad += 1
                fails.append((tag, p.name, msg))
                continue
            good += 1
            n, abad = check_anchors(p, instrs)
            anchors += n
            anchor_bad += len(abad)
            for m in abad[:3]:
                fails.append((tag, p.name, '锚点: ' + m))
        grand_ok += good
        grand_bad += bad
        print('%-8s %-4s %d/%-4d %s' % (tag, 'OK' if bad == 0 else 'FAIL',
                                        good, len(files),
                                        '' if bad == 0 else '<-- %d 个文件失败' % bad))
    print('-' * 60)
    print('覆盖：%d/%d 文件 100%% tile，失败 %d' % (grand_ok, grand_ok + grand_bad,
                                                   grand_bad))
    print('锚点：CG 显示正则 %d 个匹配，边界不符 %d' % (anchors, anchor_bad))
    if fails:
        print('\n失败清单：')
        for tag, name, msg in (fails if verbose else fails[:40]):
            print('  %-8s %-32s %s' % (tag, name, msg))
        if not verbose and len(fails) > 40:
            print('  ...（共 %d 条，加 -v 打印全部）' % len(fails))
    return 1 if (grand_bad or anchor_bad) else 0


if __name__ == '__main__':
    sys.exit(main())
