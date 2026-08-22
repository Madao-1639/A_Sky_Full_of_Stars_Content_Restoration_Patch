#!/usr/bin/env python3
"""通用 payload 生成器：计算 asset/ 相对于 backup/ 的增量。

使用固定路径约定：
  - asset/    = 封装好的游戏文件（打补丁后的完整版本）
  - backup/   = Steam 原版基线（用于计算增量）
  - payload/  = 输出增量 payload 供安装器使用
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import hashlib
import json
from tool import arcbuild

ASSET_DIR = Path('asset')
BACKUP_DIR = Path('backup')
PAYLOAD_DIR = Path('payload')

def sha256(data):
    return hashlib.sha256(data).hexdigest()

def generate_delta_arc(asset_path, backup_path, output_path):
    """生成补丁：包含 asset 相对于 backup 的新增/修改成员。

    返回补丁大小、统计信息、以及被删除的成员列表。
    """
    # 读取两个版本
    asset_members = {n.decode('utf-16-le'): (n, d)
                     for n, d in arcbuild.read_raw(asset_path)}

    if backup_path.exists():
        backup_members = {n.decode('utf-16-le'): (n, d)
                          for n, d in arcbuild.read_raw(backup_path)}
    else:
        backup_members = {}

    # 检测被删除的成员（backup 中有但 asset 中没有）
    deleted = [name for name in backup_members if name not in asset_members]

    # 增量模式：只包含新增或修改的成员
    delta = []
    added = 0
    modified = 0
    unchanged = 0

    for name, (name_bytes, data) in asset_members.items():
        if name not in backup_members:
            delta.append((name_bytes, data))
            added += 1
        else:
            _, backup_data = backup_members[name]
            if sha256(data) != sha256(backup_data):
                delta.append((name_bytes, data))
                modified += 1
            else:
                unchanged += 1

    if not delta:
        return None, {'added': 0, 'modified': 0, 'unchanged': unchanged, 'deleted': len(deleted)}, deleted

    # 写入补丁归档
    output_path.parent.mkdir(parents=True, exist_ok=True)
    arcbuild.write_arc(delta, output_path)

    return output_path.stat().st_size, {
        'added': added,
        'modified': modified,
        'unchanged': unchanged,
        'deleted': len(deleted)
    }, deleted

def main():
    print('=' * 84)
    print('通用 Payload 生成器')
    print('=' * 84)
    print(f'Asset 目录:   {ASSET_DIR}')
    print(f'Backup 目录:  {BACKUP_DIR}')
    print(f'Payload 目录: {PAYLOAD_DIR}')
    print()

    # 检查目录
    if not ASSET_DIR.exists():
        print(f'错误: Asset 目录不存在: {ASSET_DIR}')
        return 1

    if not BACKUP_DIR.exists():
        print(f'警告: Backup 目录不存在，将视所有 asset 为新增')
        BACKUP_DIR.mkdir(parents=True)

    # 清空旧 payload（避免旧文件被意外安装）
    if PAYLOAD_DIR.exists():
        import shutil
        shutil.rmtree(PAYLOAD_DIR)
    PAYLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # 需要处理的归档
    ARCHIVES = [
        ('Rio.arc', 'Rio.arc'),  # 脚本，不生成增量，直接复制
        ('Chip1.arc', 'Chip1_patch.arc'),
        ('Chip1A.arc', 'Chip1A_patch.arc'),
        ('Chip2.arc', 'Chip2_patch.arc'),
        ('Chip3.arc', 'Chip3_patch.arc'),
        ('Chip3A.arc', 'Chip3A_patch.arc'),
        ('Chip3B.arc', 'Chip3B_patch.arc'),
        ('Graphic.arc', 'Graphic_patch.arc'),
        ('Voice.arc', 'Voice_patch.arc'),
        ('Voice1.arc', 'Voice1_patch.arc'),
    ]

    print('生成 payload:')
    print()

    total_size = 0
    all_deletes = {}  # 收集所有删除清单

    for asset_name, output_name in ARCHIVES:
        asset_path = ASSET_DIR / asset_name
        backup_path = BACKUP_DIR / asset_name
        output_path = PAYLOAD_DIR / output_name

        if not asset_path.exists():
            print(f'  [SKIP] {asset_name}: 不存在')
            continue

        # Rio.arc 直接复制（脚本归档通常全量替换）
        if asset_name == 'Rio.arc':
            import shutil
            shutil.copy2(asset_path, output_path)
            size = output_path.stat().st_size
            total_size += size
            print(f'  [OK] {output_name}: {size:,} bytes (全量)')
            continue

        # 其他归档生成增量（不传 delete_list_path，由主程序收集）
        size, stats, deleted = generate_delta_arc(asset_path, backup_path, output_path)

        if size is None:
            print(f'  [SKIP] {output_name}: 无变化，跳过')
            if output_path.exists():
                output_path.unlink()
        else:
            total_size += size
            print(f'  [OK] {output_name}: {size:,} bytes')
            print(f'      新增={stats["added"]} 修改={stats["modified"]} '
                  f'未变={stats["unchanged"]} 删除={stats["deleted"]}')

            # 收集删除清单
            if deleted:
                all_deletes[output_name] = deleted

    # 处理中文补丁
    zh_asset = ASSET_DIR / 'zh-CN'
    zh_payload = PAYLOAD_DIR / 'zh-CN'

    if zh_asset.exists():
        print()
        print('  处理中文补丁:')
        zh_payload.mkdir(exist_ok=True)

        for zh_arc in zh_asset.glob('*.arc'):
            import shutil
            dst = zh_payload / zh_arc.name
            shutil.copy2(zh_arc, dst)
            size = dst.stat().st_size
            total_size += size
            print(f'    [OK] zh-CN/{zh_arc.name}: {size:,} bytes')


    # 生成统一元数据文件
    print()
    print('生成元数据文件...')
    metadata = {}

    for asset_name, _ in ARCHIVES:
        asset_path = ASSET_DIR / asset_name
        backup_path = BACKUP_DIR / asset_name

        if not asset_path.exists():
            continue

        # 读取资源
        asset_members = {n.decode('utf-16-le'): d for n, d in arcbuild.read_raw(asset_path)}
        backup_members = {n.decode('utf-16-le'): d for n, d in arcbuild.read_raw(backup_path)} if backup_path.exists() else {}

        # 按 asset 顺序构建成员列表，记录每个成员的修改类型
        members_with_type = []
        for n, _ in arcbuild.read_raw(asset_path):
            name = n.decode('utf-16-le')

            if name not in backup_members:
                # 新增的成员
                member_type = 'added'
            elif sha256(asset_members[name]) != sha256(backup_members[name]):
                # 被修改的成员
                member_type = 'modified'
            else:
                # 保留的成员
                member_type = 'keep'

            members_with_type.append({
                'name': name,
                'type': member_type
            })

        metadata[asset_name] = {
            'checksum': sha256(asset_path.read_bytes()),
            'members': members_with_type
        }

    metadata_file = PAYLOAD_DIR / 'METADATA.json'
    metadata_file.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'已保存至: {metadata_file}')

    print()
    print('=' * 84)
    print(f'Payload 总大小: {total_size:,} bytes ({total_size/1024/1024:.1f} MB)')
    print(f'已保存至: {PAYLOAD_DIR}')
    print()
    print('下一步: bash script/pack.sh')

    return 0

if __name__ == '__main__':
    main()
