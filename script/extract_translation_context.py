"""为 3 个缺失中文翻译的新增 H 场景提取切入前/切出后的中文语境（来自入口/出口 _E 脚本的 zh-CN .lng）

入口/出口关系取自 tmp/phase3_call_chain_report.md 的核实结果：
  yozora_hika_103d_H  <- yozora_hika_103c_E  -> YOZORA_HIKA_103E_E
  yozora_hika_110c_H  <- yozora_hika_110b_E  -> YOZORA_HIKA_110D_E
  yozora_saya_101j_H  <- yozora_saya_101i_E  -> YOZORA_SAYA_102_E
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tool import arcbuild, lng

ZH_RIO = Path('asset/zh-CN/Rio.arc')
OUT = Path('tmp/translation_context.md')

TARGETS = [
    ('yozora_hika_103d_H', 'yozora_hika_103c_E', 'yozora_hika_103e_E'),
    ('yozora_hika_110c_H', 'yozora_hika_110b_E', 'yozora_hika_110d_E'),
    ('yozora_saya_101j_H', 'yozora_saya_101i_E', 'yozora_saya_102_E'),
]

N_LINES = 20


def main():
    zh_rio = arcbuild.read_raw(ZH_RIO)
    zh_dict = {name.decode('utf-16le'): data for name, data in zh_rio}

    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('# H 场景切换上下文（中文，供翻译参照语境）\n\n')

        for h_stem, entry_stem, exit_stem in TARGETS:
            f.write(f'## {h_stem}\n\n')

            entry_lng = f'{entry_stem}.lng'
            exit_lng = f'{exit_stem}.lng'

            f.write(f'### 入口场景 {entry_stem} 结尾 {N_LINES} 句（切入前）\n\n')
            if entry_lng in zh_dict:
                strings = lng.parse_lng(zh_dict[entry_lng])
                tail = strings[-N_LINES:]
                for i, s in enumerate(tail, start=len(strings) - len(tail)):
                    f.write(f'{i}: {s}\n')
            else:
                f.write(f'[!] {entry_lng} not found in zh-CN/Rio.arc\n')
            f.write('\n')

            f.write(f'### 出口场景 {exit_stem} 开头 {N_LINES} 句（切出后）\n\n')
            if exit_lng in zh_dict:
                strings = lng.parse_lng(zh_dict[exit_lng])
                head = strings[:N_LINES]
                for i, s in enumerate(head):
                    f.write(f'{i}: {s}\n')
            else:
                f.write(f'[!] {exit_lng} not found in zh-CN/Rio.arc\n')
            f.write('\n---\n\n')

    print(f'[OK] Written {OUT}')


if __name__ == '__main__':
    main()
