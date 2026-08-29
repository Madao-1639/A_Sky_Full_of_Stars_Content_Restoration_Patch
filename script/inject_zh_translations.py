"""将临时中文翻译打包为 .lng 并注入 zh-CN/Rio.arc

前置条件：
  tmp/embedded_text/<script>.json      - 从脚本提取的英文原文（0..N-1 密集索引）
  tmp/embedded_text/<script>.zh.json   - 对应的中文翻译（同长度、同顺序）

用途：为 Phase 2 新导入的 3 个 _H 脚本（此前 zh-CN/Rio.arc 中没有对应 .lng，
引擎回退显示 Miazora 内嵌的英文原文）补充临时中文 .lng，格式与其余 295 个
已有 .lng 完全一致（tool/lng.py: u32 count + u16 长度表 + UTF-16LE^0xCE 字符串）。

幂等：若目标 .lng 已存在且内容与本次生成结果字节一致，跳过写入。
"""

import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tool import arcbuild, lng

ZH_RIO = Path('asset/zh-CN/Rio.arc')
BACKUP_ZH_RIO = Path('asset/zh-CN/Rio.arc.before_translation_inject')
EMBEDDED_DIR = Path('tmp/embedded_text')

TARGETS = [
    'yozora_hika_103d_H',
    'yozora_hika_110c_H',
    'yozora_saya_101j_H',
]


def main():
    print('=== Inject Temporary Chinese Translations into zh-CN/Rio.arc ===\n')

    # 1. 校验翻译文件齐备且行数匹配
    print('1. Validate translation files')
    payloads = {}
    for stem in TARGETS:
        en_path = EMBEDDED_DIR / f'{stem}.json'
        zh_path = EMBEDDED_DIR / f'{stem}.zh.json'

        if not en_path.exists():
            print(f'  [!] Missing source: {en_path}')
            return 1
        if not zh_path.exists():
            print(f'  [!] Missing translation: {zh_path}')
            return 1

        with open(en_path, encoding='utf-8') as f:
            en_list = json.load(f)
        with open(zh_path, encoding='utf-8') as f:
            zh_list = json.load(f)

        if len(en_list) != len(zh_list):
            print(f'  [!] {stem}: length mismatch EN={len(en_list)} ZH={len(zh_list)}')
            return 1

        # 检查 %K%P 结尾保留
        bad = [i for i, s in enumerate(zh_list) if not s.endswith('%K%P')]
        if bad:
            print(f'  [!] {stem}: {len(bad)} lines missing trailing %K%P, e.g. index {bad[0]}: {zh_list[bad[0]]!r}')
            return 1

        print(f'  [OK] {stem}: {len(zh_list)} lines validated')
        payloads[stem] = zh_list

    # 2. 备份
    print(f'\n2. Backup {ZH_RIO} -> {BACKUP_ZH_RIO}')
    import shutil
    shutil.copy2(ZH_RIO, BACKUP_ZH_RIO)

    # 3. 加载现有 zh-CN/Rio.arc
    print('\n3. Load zh-CN/Rio.arc')
    zh_rio = arcbuild.read_raw(ZH_RIO)
    zh_dict = {name.decode('utf-16le'): (name, data) for name, data in zh_rio}

    # 4. 编码并写入/替换
    print('\n4. Encode and inject .lng members')
    added = 0
    replaced = 0
    for stem, zh_list in payloads.items():
        lng_name = f'{stem}.lng'
        encoded = lng.encode_lng(zh_list)

        # 回读校验
        roundtrip = lng.parse_lng(encoded)
        if roundtrip != zh_list:
            print(f'  [!] {lng_name}: roundtrip verification FAILED')
            return 1

        name_bytes = lng_name.encode('utf-16le')

        if lng_name in zh_dict:
            old_name_bytes, old_data = zh_dict[lng_name]
            if old_data == encoded:
                print(f'  [SKIP] {lng_name}: already up to date (idempotent)')
                continue
            print(f'  [REPLACE] {lng_name}: {len(old_data)} -> {len(encoded)} bytes')
            zh_dict[lng_name] = (old_name_bytes, encoded)
            replaced += 1
        else:
            print(f'  [ADD] {lng_name}: {len(encoded)} bytes, {len(zh_list)} strings')
            zh_dict[lng_name] = (name_bytes, encoded)
            added += 1

    if added == 0 and replaced == 0:
        print('\n[OK] Nothing to do, all translations already injected')
        return 0

    # 5. 写回
    print(f'\n5. Write back zh-CN/Rio.arc ({added} added, {replaced} replaced)')
    members = [(name_bytes, data) for name_bytes, data in zh_dict.values()]
    arcbuild.write_arc(members, ZH_RIO)

    # 6. 验证归档结构
    print('\n6. Verify archive integrity')
    cnt, fsize, end = arcbuild.verify(ZH_RIO)
    print(f'  [OK] verify passed: count={cnt} fsize={fsize}')

    print('\n[OK] Translation injection completed')
    print(f'  Backup: {BACKUP_ZH_RIO}')
    print(f'  Output: {ZH_RIO}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
