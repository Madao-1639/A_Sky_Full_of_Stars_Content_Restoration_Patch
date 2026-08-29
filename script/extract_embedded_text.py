"""提取 _H 脚本中内嵌的回退文本（char\\x00 标记后、%K%P 结尾），按 0x14 指令的 u16 索引排列

用途：为缺少 zh-CN .lng 的新增脚本（yozora_hika_103d_H / yozora_hika_110c_H /
yozora_saya_101j_H）生成待翻译的文本清单。

格式（已通过 yozora_saya_102c_H.ws2 等已有中文脚本验证）：
    0x14 <idx:u16> <flag:u16> "char\\x00" <SJIS/ASCII text>"%K%P"

idx 是该行在 zh-CN .lng 中的字符串索引；引擎优先查 .lng[idx]，缺失则回退显示脚本内嵌文本。
"""

import sys
import re
import struct
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tool import arcbuild, ws2

CURRENT_RIO = Path('asset/Rio.arc')
OUTPUT_DIR = Path('tmp/embedded_text')

PATTERN = re.compile(rb'\x14(..)(..)char\x00(.*?)%K%P', re.S)

TARGET_SCRIPTS = [
    'yozora_hika_103d_H.ws2',
    'yozora_hika_110c_H.ws2',
    'yozora_saya_101j_H.ws2',
]


def extract(decoded):
    """返回 {idx: text} 密集映射，并报告重复/缺口"""
    by_idx = {}
    order = []
    for m in PATTERN.finditer(decoded):
        idx = struct.unpack('<H', m.group(1))[0]
        text = (m.group(3) + b'%K%P').decode('shift_jis', errors='replace')
        order.append((idx, text))
        if idx not in by_idx:
            by_idx[idx] = text
        elif by_idx[idx] != text:
            print(f'  [!] idx={idx} 内容不一致: {by_idx[idx]!r} vs {text!r}')
    return by_idx, order


def main():
    print('=== Extract Embedded Fallback Text ===\n')
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    rio = arcbuild.read_raw(CURRENT_RIO)
    rio_dict = {name.decode('utf-16le'): data for name, data in rio}

    for script_name in TARGET_SCRIPTS:
        print(f'Processing {script_name}...')
        decoded = ws2.decode(rio_dict[script_name])

        by_idx, order = extract(decoded)

        max_idx = max(by_idx.keys()) if by_idx else -1
        expected = set(range(max_idx + 1))
        actual = set(by_idx.keys())
        missing = expected - actual

        print(f'  Total occurrences: {len(order)}')
        print(f'  Unique indices: {len(by_idx)}, max_idx: {max_idx}')
        if missing:
            print(f'  [!] Missing indices: {sorted(missing)}')
        else:
            print(f'  [OK] Dense range 0..{max_idx}')

        # 输出为 JSON，供翻译使用
        dense_list = [by_idx.get(i, '') for i in range(max_idx + 1)]
        out_path = OUTPUT_DIR / script_name.replace('.ws2', '.json')
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(dense_list, f, ensure_ascii=False, indent=1)

        print(f'  -> {out_path}\n')

    print('[OK] Extraction complete')


if __name__ == '__main__':
    main()
