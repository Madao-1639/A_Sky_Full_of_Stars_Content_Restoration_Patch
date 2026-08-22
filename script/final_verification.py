#!/usr/bin/env python3
"""最终验收：检查调用链完整性与资源存在性。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import re, hashlib
from collections import Counter
from tool import arcbuild, ws2

ASSET = Path('asset')

def sha(b):
    return hashlib.sha256(b).hexdigest()

# 加载所有归档
archives = {}
for arc in ['Rio.arc', 'Chip1.arc', 'Chip1A.arc', 'Chip2.arc', 'Chip3.arc',
            'Chip3A.arc', 'Chip3B.arc', 'Graphic.arc']:
    p = ASSET / arc
    if p.exists():
        archives[arc] = {n.decode('utf-16-le').upper(): (n.decode('utf-16-le'), d)
                         for n, d in arcbuild.read_raw(p)}

rio = archives['Rio.arc']

print('=' * 84)
print('【检查 1】saya_107 调用链完整性')
print('=' * 84)

chain = [
    ('yozora_saya_107b_H.ws2', '0x07', 'YOZORA_SAYA_107C_E'),
    ('yozora_saya_107c_E.ws2', '0x07', 'YOZORA_SAYA_107D_H'),
    ('yozora_saya_107d_H.ws2', '0x07', 'YOZORA_SAYA_107E_E'),
]

print('预期调用链:')
for caller, op, target in chain:
    print(f'  {caller} --{op}--> {target}')

print('\n实际验证:')
all_ok = True
for caller, op, target in chain:
    if caller.upper() not in rio:
        print(f'  FAIL {caller} 不存在')
        all_ok = False
        continue

    _, raw = rio[caller.upper()]
    data = ws2.decode(raw)

    if op == '0x07':
        pattern = b'\x07' + target.encode('ascii') + b'\x00'
    else:
        pattern = b'\x04' + target.encode('ascii') + b'\x00'

    count = data.count(pattern)
    status = 'OK' if count > 0 else 'FAIL'
    print(f'  [{status}] {caller} 调用 {target}: {count} 处')
    if count == 0:
        all_ok = False

# 检查目标脚本存在性
print('\n目标脚本存在性:')
targets = ['YOZORA_SAYA_107C_E.WS2', 'YOZORA_SAYA_107D_H.WS2', 'YOZORA_SAYA_107E_E.WS2']
for t in targets:
    exists = t in rio
    status = 'OK' if exists else 'FAIL'
    print(f'  {status} {t}: {"存在" if exists else "缺失"}')
    if not exists:
        all_ok = False

print(f'\n调用链完整性: {"OK 通过" if all_ok else "FAIL 失败"}')

print('\n' + '=' * 84)
print('【检查 2】新增原版脚本的资源完整性')
print('=' * 84)

# 所有新增的原版脚本（来自 Resto 1.1.0）
original_scripts = [
    'yozora_hika_103f.ws2',
    'yozora_hika_103g_H.ws2',
    'yozora_ori_115_H.ws2',
    'yozora_saya_107b_H.ws2',
    'yozora_saya_107d_H.ws2',
]

# 收集所有 PNA 引用（使用 0x34 显示指令精确解析）
pna_refs = Counter()
DISPLAY_PATTERN = re.compile(rb'\x34([^\x00]{2,12})\x00([^\x00]+)\.PNA\x00\x01\x01', re.S | re.I)

for script in original_scripts:
    if script.upper() not in rio:
        continue
    _, raw = rio[script.upper()]
    data = ws2.decode(raw)

    for m in DISPLAY_PATTERN.finditer(data):
        stem_bytes = m.group(2)
        try:
            # 尝试 Shift-JIS 解码（游戏使用的编码）
            stem = stem_bytes.decode('shift-jis')
        except:
            # 失败则用 ASCII
            try:
                stem = stem_bytes.decode('ascii')
            except:
                continue
        pna_refs[stem] += 1

print(f'新增原版脚本引用的 PNA（共 {len(pna_refs)} 种）:')
for pna, cnt in sorted(pna_refs.items()):
    print(f'  {pna}.pna: {cnt} 次引用')

# 检查资源存在性
print('\n资源存在性检查:')
missing = []
for pna in sorted(pna_refs.keys()):
    pna_name = (pna + '.PNA').upper()
    found = False
    location = None

    for arc_name, members in archives.items():
        if pna_name in members:
            found = True
            location = arc_name
            break

    status = 'OK' if found else 'FAIL'
    info = f'({location})' if found else '缺失'
    print(f'  {status} {pna}.pna: {info}')

    if not found:
        missing.append(pna)

if missing:
    print(f'\nFAIL 缺失 {len(missing)} 个资源: {missing}')
    all_ok = False
else:
    print('\nOK 所有引用的资源都存在')

print('\n' + '=' * 84)
print('【检查 3】冗余资源检测')
print('=' * 84)

# 检查是否有未被引用的 ORG_ 资源
print('ORG_ 资源使用情况:')
org_resources = {}
for arc_name, members in archives.items():
    for name_upper, (name, data) in members.items():
        if name.upper().startswith('ORG_') and name.upper().endswith('.PNA'):
            stem = name[:-4].upper()  # 去掉 .PNA
            org_resources[stem] = (arc_name, len(data))

all_scripts = {n.upper(): d for n, d in rio.values()}
used_orgs = set()
for script_name, raw in all_scripts.items():
    if not script_name.endswith('.WS2'):
        continue
    data = ws2.decode(raw)
    # capture ORG_ names including Shift-JIS Japanese ones (ORG_Aひかり_*, ORG_B沙夜_*)
    for m in re.finditer(rb'(ORG_[^\x00]+?)\.PNA', data):
        used_orgs.add(m.group(1))

for org_stem in sorted(org_resources.keys()):
    used = org_stem.encode('shift_jis') in used_orgs
    arc, size = org_resources[org_stem]
    status = 'OK' if used else 'FAIL'
    usage = '被引用' if used else '未被引用（冗余）'
    print(f'  {status} {org_stem}.pna ({arc}, {size:,} bytes): {usage}')
    if not used:
        all_ok = False

print('\n' + '=' * 84)
print('【检查 4】Rio.arc 成员统计')
print('=' * 84)

members_count = len(rio)
saya_107_count = len([n for n in rio.keys() if 'SAYA_107' in n])

print(f'总成员数: {members_count}')
print(f'saya_107 系列: {saya_107_count} 个')
print(f'  - yozora_saya_107_E.ws2')
print(f'  - yozora_saya_107a_E.ws2')
print(f'  - yozora_saya_107b_H.ws2')
print(f'  - yozora_saya_107c_E.ws2 (已修改跳转)')
print(f'  - yozora_saya_107d_H.ws2')
print(f'  - yozora_saya_107e_E.ws2')

print('\n' + '=' * 84)
print('【最终结论】')
print('=' * 84)
if all_ok:
    print('OK 所有检查通过，可以推送')
else:
    print('FAIL 存在问题，需要修复')

print('\n生成校验和文件...')
checksums = []
for arc in ['Rio.arc', 'Chip3.arc', 'Chip3A.arc', 'Chip3B.arc',
            'Graphic.arc', 'Voice.arc', 'Voice1.arc']:
    p = ASSET / arc
    if p.exists():
        h = sha(p.read_bytes())
        checksums.append(f'{h}  {arc}')

zh_rio = ASSET / 'zh-CN' / 'Rio.arc'
if zh_rio.exists():
    h = sha(zh_rio.read_bytes())
    checksums.append(f'{h}  zh-CN/Rio.arc')

checksum_file = ASSET / 'SHA256SUMS'
checksum_file.write_text('\n'.join(checksums) + '\n', encoding='utf-8')
print(f'OK 已生成 {checksum_file.name}')
