"""修复因资源改名（变长插入）导致的 EVRET field1/field2 绝对偏移错位

根因：complete_org_rewrites.py 在脚本中部插入 ORG_ 前缀（每处 +4 字节），
但未同步更新 EVRET 结构里指向 gallery 指令的绝对 u32 偏移，
导致引擎按旧偏移读取，读到错位数据，场景结束后黑屏卡死（按钮仍可交互）。

规则（doc/file-formats.md）：
  <field1 u32> 01 82 6e 00 00 00 <float> 00 00 <field2 u32> 07 EVRET 00 0b <gallery> 01 ...
  field1 (07 前 20 字节) 和 field2 (07 前 4 字节) 必须等于 gallery 指令 (0x0b) 的绝对偏移
  即 evret_marker_pos + 7 （EVRET 标记 "\x07EVRET\x00" 长度为 7）
"""

import sys
import struct
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tool import arcbuild, ws2

CURRENT_RIO = Path('asset/Rio.arc')
BACKUP_RIO = Path('asset/Rio.arc.before_evret_fix')

# 受影响的脚本（本次修复目标）
AFFECTED_SCRIPTS = [
    'yozora_saya_101j_H.ws2',
    'yozora_ori_118_H.ws2',
    'yozora_ori_123_H.ws2',
    'yozora_ori_129_H.ws2',
]


def fix_evret_offset(decoded):
    """就地修复单个脚本的 EVRET field1/field2，返回 (new_decoded, old1, old2, new_val) 或 None"""
    evret_pos = decoded.find(b'\x07EVRET\x00')
    if evret_pos == -1:
        return None

    gallery_pos = evret_pos + 7  # "\x07EVRET\x00" 长度为 7

    field2_off = evret_pos - 4
    field1_off = evret_pos - 20

    old_field2 = struct.unpack('<I', decoded[field2_off:field2_off + 4])[0]
    old_field1 = struct.unpack('<I', decoded[field1_off:field1_off + 4])[0]

    if old_field1 == gallery_pos and old_field2 == gallery_pos:
        return None  # 已经正确，无需修复

    new_bytes = bytearray(decoded)
    new_bytes[field1_off:field1_off + 4] = struct.pack('<I', gallery_pos)
    new_bytes[field2_off:field2_off + 4] = struct.pack('<I', gallery_pos)

    return bytes(new_bytes), old_field1, old_field2, gallery_pos


def main():
    print('=== Fix EVRET Absolute Offset Corruption ===\n')

    print(f'1. Backup {CURRENT_RIO} -> {BACKUP_RIO}')
    import shutil
    shutil.copy2(CURRENT_RIO, BACKUP_RIO)

    print('\n2. Load Rio.arc')
    rio = arcbuild.read_raw(CURRENT_RIO)
    rio_dict = {name.decode('utf-16le'): (name, data) for name, data in rio}

    print('\n3. Scan and fix all _H scripts (not just the known-affected list, for safety)')

    fixed_count = 0
    checked_count = 0

    for script_name, (name_bytes, script_data) in list(rio_dict.items()):
        if not script_name.lower().endswith('.ws2') or '_h.' not in script_name.lower():
            continue

        checked_count += 1
        decoded = ws2.decode(script_data)

        result = fix_evret_offset(decoded)
        if result is None:
            print(f'  [OK] {script_name}: offsets already correct')
            continue

        new_decoded, old1, old2, new_val = result
        print(f'  [FIX] {script_name}: field1 {old1}->{new_val}, field2 {old2}->{new_val} (delta {new_val-old1})')

        # 编码回去
        encoded = ws2.encode(new_decoded)

        # 验证往返
        verify = ws2.decode(encoded)
        if verify != new_decoded:
            print(f'    [!] Roundtrip verification FAILED, aborting')
            return 1

        # 再次验证修复后偏移正确
        recheck = fix_evret_offset(verify)
        if recheck is not None:
            print(f'    [!] Post-fix verification FAILED, offsets still wrong')
            return 1

        rio_dict[script_name] = (name_bytes, encoded)
        fixed_count += 1

    print(f'\n  Checked {checked_count} _H scripts, fixed {fixed_count}')

    if fixed_count == 0:
        print('\n[OK] No fixes needed, all EVRET offsets already correct')
        return 0

    print('\n4. Write back to Rio.arc')
    members = [(name_bytes, data) for name_bytes, data in rio_dict.values()]
    arcbuild.write_arc(members, CURRENT_RIO)

    print('\n[OK] EVRET offset fix completed')
    print(f'  Backup: {BACKUP_RIO}')
    print(f'  Output: {CURRENT_RIO}')
    print(f'  Fixed scripts: {fixed_count}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
