"""盘点 NameTable.txt 里**没有被任何脚本引用**的映射（只读，除非 --apply）。

「在用」判定（保守）：
  - 精确命中某个脚本的 `0x15` 前缀；或
  - 是某个在用前缀的**组成部分**（前缀匹配，保全 `%LFひかり・沙夜` 这类合称的分解查找）

用法: python script/checks/prune_nametable.py [--apply]
"""
import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tool import arcbuild, ws2, ws2disasm                            # noqa: E402

RIO = ROOT / 'asset' / 'Rio.arc'
ZH = ROOT / 'asset' / 'zh-CN' / 'Rio.arc'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--identity', action='store_true',
                    help='同时删除**恒等映射**（键==值）：引擎查不到键时原样显示名字，'
                         '故 k→k 是冗余的（依据：日文原版构建根本没有 NameTable.txt）')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    used = set()
    for nb, d in arcbuild.read_raw(RIO):
        if not nb.decode('utf-16le').upper().endswith('.WS2'):
            continue
        for i in ws2disasm.disassemble(ws2.decode(d)):
            if i.opcode == 0x15:
                p = i.fields.get('prefix') or ''
                if p:                      # 收集**所有**前缀（不止 %LF：也可能是 %LC…）
                    used.add(p)
    zh = arcbuild.read_raw(ZH)
    zd = {nb.decode('utf-16le'): (nb, d) for nb, d in zh}
    nt = zd['NameTable.txt'][1].decode('utf-16le')
    rows = [ln for ln in nt.split('\r\n') if '\t' in ln]
    pairs = [ln.split('\t', 1) for ln in rows if '\t' in ln]
    exact_unused, comp_unused, ident = [], [], []
    for k, v in pairs:
        if k not in used and not any(p.startswith(k) for p in used):
            exact_unused.append(k)
        elif k == v:
            ident.append(k)                # 键==值 → 冗余（引擎查不到键时原样显示名字）
    ident = [k for k in ident if k not in exact_unused and k[3:].strip()]
    #  ^ 跳过「名字为空/全空白」的官方行（如 `%LF　`），那是官方的空名标记，不属本次清理
    print('NameTable %d 条；脚本在用前缀 %d 种' % (len(rows), len(used)))
    print('\n【真正无用·未被引用】%d 条：%s' % (len(exact_unused), exact_unused))
    print('【恒等映射（键==值，冗余）】%d 条：%s' % (len(ident), ident))
    print('【保留：作为合称前缀的组成部分】%s' % comp_unused)

    drop = set(exact_unused) | (set(ident) if a.identity else set())
    if not drop:
        print('\n无需删除')
        return 0
    if not a.apply:
        print('（dry-run，将删除 %d 条；加 --apply 执行）' % len(drop))
        return 0
    new_nt = '\r\n'.join(ln for ln in nt.split('\r\n') if ln.split('\t')[0] not in drop)
    b = ZH.with_name(ZH.name + '.before_nametable_prune')
    if not b.exists():
        shutil.copy2(ZH, b)
        print('已备份 %s' % b.name)
    zd['NameTable.txt'] = ('NameTable.txt'.encode('utf-16le'), new_nt.encode('utf-16le'))
    arcbuild.write_arc(list(zd.values()), ZH)
    arcbuild.verify(ZH, expect_count=len(zd))
    back = {nb.decode('utf-16le'): d for nb, d in arcbuild.read_raw(ZH)}
    lines = [ln for ln in back['NameTable.txt'].decode('utf-16le').split('\r\n') if '\t' in ln]
    print('NameTable %d -> %d 条；删除 %s' % (len(rows), len(lines), sorted(drop)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
