"""提取 _H 脚本中内嵌的回退文本（char\\x00 标记后、%K%P 结尾），按 0x14 指令的 u16 索引排列

用途：为尚无 zh-CN .lng 的还原场景生成待翻译的文本清单。目标脚本由
resource/scenes.json 推出（尚无 .lng 的引入场景），不再硬编码脚本名。

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

from tool import arcbuild, resources, ws2

CURRENT_RIO = Path('asset/Rio.arc')
ZH_RIO = Path('asset/zh-CN/Rio.arc')
OUTPUT_DIR = Path('tmp/embedded_text')

PATTERN = re.compile(rb'\x14(..)(..)char\x00(.*?)%K%P', re.S)


def missing_lng_scenes():
    """尚无 zh-CN .lng 的还原场景，返回 .ws2 文件名（按 scenes.json 顺序）。"""
    have = {name.decode('utf-16le').upper() for name, _ in arcbuild.read_raw(ZH_RIO)}
    return [scene['id'] + '.ws2'
            for scene in resources.load('scenes.json')['scenes']
            if (scene['id'] + '.lng').upper() not in have]


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

    targets = missing_lng_scenes()
    if not targets:
        print('[OK] 所有还原场景均已有 zh-CN .lng，无需提取')
        return
    print(f'待提取: {len(targets)} 个脚本\n')

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    rio = arcbuild.read_raw(CURRENT_RIO)
    rio_dict = {name.decode('utf-16le'): data for name, data in rio}

    for script_name in targets:
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
