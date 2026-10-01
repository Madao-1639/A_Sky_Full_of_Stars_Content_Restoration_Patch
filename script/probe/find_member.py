"""在 asset/ 与 backup/ 的所有 .arc 里查找指定成员名（大小写不敏感，按 UTF-8 关键字文件）。

存在的权威判据是 backup/（Steam 原版）与 asset/（补丁）两侧都查，避免"只扫一侧"的误报。

用法: python script/probe/find_member.py <kw-file>
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tool import arcbuild


def main():
    kws = [ln.strip().upper() for ln in Path(sys.argv[1]).read_text(encoding='utf-8').splitlines()
           if ln.strip() and not ln.startswith('#')]
    arcs = []
    for base in ('asset', 'backup'):
        arcs += sorted((ROOT / base).glob('*.arc'))
        arcs += sorted((ROOT / base).glob('**/*.arc'))
    hit_any = False
    for arc in arcs:
        try:
            mem = arcbuild.read_raw(arc)
        except Exception as e:
            print('  (%s 读取失败 %s)' % (arc.relative_to(ROOT), type(e).__name__))
            continue
        for nb, d in mem:
            n = nb.decode('utf-16le')
            if any(k in n.upper() for k in kws):
                hit_any = True
                print('%-34s %-30s %10d 字节' % (arc.relative_to(ROOT), n, len(d)))
    if not hit_any:
        print('未找到（关键字 %s）' % kws)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
