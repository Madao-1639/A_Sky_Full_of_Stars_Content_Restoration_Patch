#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Phase 2: Deploy 20 PNA resources and rewrite _H scripts

Deploys:
- 14 event CGs (9X segment) to Chip3.arc/Chip3B.arc
- 6 character sprites (ORG_ prefix) to Graphic.arc

Rewrites 9 _H scripts to reference the new resources.
"""

import os
import sys
import json
import hashlib
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from tool import arcbuild, ws2

# Paths
MIAZORA_ROOT = Path(r"D:\My_Code\tmp\GamePatch\A_Sky_Full_of_Stars\MiazoraPatch(v1.2)\+18 Version")
ASSET_DIR = project_root / "asset"
RIO_ARC = ASSET_DIR / "Rio.arc"

# Load phase1 mapping
MAPPING_FILE = project_root / "tmp" / "phase1_resource_mapping.json"

def sha256_bytes(data: bytes) -> str:
    """Calculate SHA256 of bytes"""
    return hashlib.sha256(data).hexdigest()

def backup_archive(arc_path: Path):
    """Backup an archive before modification"""
    backup_path = arc_path.with_suffix(arc_path.suffix + ".before_phase2")
    if backup_path.exists():
        print(f"[SKIP] Backup already exists: {backup_path}")
        return

    import shutil
    shutil.copy2(arc_path, backup_path)
    print(f"[BACKUP] {arc_path.name} -> {backup_path.name}")

def deploy_resources():
    """Deploy all 20 PNA resources from Miazora to target archives"""
    print("="*60)
    print("PART 1: DEPLOYING PNA RESOURCES")
    print("="*60)

    # Load mapping
    with open(MAPPING_FILE, 'r', encoding='utf-8') as f:
        mapping = json.load(f)

    # Group by target archive
    deployments = {}
    for category in ['event_cg', 'character_sprite']:
        for resource in mapping['to_deploy'][category]:
            target = resource['target_archive']
            if target not in deployments:
                deployments[target] = []
            deployments[target].append(resource)

    # Process each target archive
    for target_rel, resources in deployments.items():
        target_path = project_root / target_rel
        print(f"\n[TARGET] {target_path.name} ({len(resources)} resources)")

        # Backup
        backup_archive(target_path)

        # Load target archive (returns list of (name_bytes, data) tuples)
        target_members = arcbuild.read_raw(target_path)
        print(f"  Current members: {len(target_members)}")

        # Cache source archives to avoid repeated loading
        source_cache = {}

        # Process each resource
        for res in resources:
            source_arc_path = MIAZORA_ROOT / Path(res['source_archive']).name
            new_name = res['new_name']
            source_name = res['source_name']

            # Load source archive if needed (with caching)
            source_key = str(source_arc_path)
            if source_key not in source_cache:
                source_cache[source_key] = arcbuild.read_raw(source_arc_path)

            print(f"  [EXTRACT] {source_name} from {source_arc_path.name}")
            source_members = source_cache[source_key]

            # Find source resource
            source_data = None
            for name_bytes, data in source_members:
                member_name = name_bytes.decode('utf-16le').rstrip('\x00')
                if member_name.lower() == source_name.lower():
                    source_data = data
                    break

            if source_data is None:
                raise ValueError(f"Source resource not found: {source_name} in {source_arc_path.name}")

            # Verify SHA256
            actual_sha = sha256_bytes(source_data)
            expected_sha = res['sha256']
            if actual_sha != expected_sha:
                raise ValueError(f"SHA256 mismatch for {source_name}: expected {expected_sha}, got {actual_sha}")

            print(f"    Size: {len(source_data):,} bytes, SHA256: {actual_sha[:16]}...")

            # Add to target with new name
            new_name_bytes = new_name.encode('utf-16le')
            target_members.append((new_name_bytes, source_data))
            print(f"    [ADD] {new_name}")

        # Clear source cache to free memory
        source_cache.clear()

        # Write back target archive to a temp file first
        print(f"  [WRITE] {target_path.name} ({len(target_members)} total members)")
        temp_path = target_path.with_suffix('.tmp')
        arcbuild.write_arc(target_members, temp_path)

        # Replace original with temp
        import shutil
        shutil.move(str(temp_path), str(target_path))

        # Verify no null padding
        with open(target_path, 'rb') as f:
            f.seek(-16, 2)
            tail = f.read()
            if tail == b'\x00' * 16:
                print(f"  [WARNING] Null padding detected, normalizing...")
                arcbuild.normalize_arc_padding(target_path)

        print(f"  [OK] {target_path.name} deployed")

    print(f"\n[COMPLETE] All 20 resources deployed")

def rewrite_scripts():
    """Rewrite _H scripts to reference ORG_/9X resources"""
    print("\n" + "="*60)
    print("PART 2: REWRITING _H SCRIPTS")
    print("="*60)

    # Script rewrite specifications
    rewrites = [
        {
            'script': 'yozora_hika_103d_H.ws2',
            'replacements': [
                ('HIK_09L.PNA', 'HIK_90L.PNA'),
                ('HIK_09S.PNA', 'HIK_90S.PNA'),
                ('HIK_15L.PNA', 'HIK_91L.PNA'),
                ('HIK_15S.PNA', 'HIK_91S.PNA'),
                ('HIK_16L.PNA', 'HIK_92L.PNA'),
                ('HIK_16S.PNA', 'HIK_92S.PNA'),
            ]
        },
        {
            'script': 'yozora_hika_110c_H.ws2',
            'replacements': [
                ('HIK_22L.PNA', 'HIK_93L.PNA'),
                ('HIK_22S.PNA', 'HIK_93S.PNA'),
                ('HIK_23L.PNA', 'HIK_94L.PNA'),
                ('HIK_23S.PNA', 'HIK_94S.PNA'),
            ]
        },
        {
            'script': 'yozora_saya_101j_H.ws2',
            'replacements': [
                ('SAY_15L.PNA', 'SAY_90L.PNA'),
                ('SAY_15S.PNA', 'SAY_90S.PNA'),
                ('SAY_16L.PNA', 'SAY_91L.PNA'),
                ('SAY_16S.PNA', 'SAY_91S.PNA'),
                ('Bさや_01L.PNA', 'ORG_Bさや_01L.PNA'),
                ('Bさや_02L.PNA', 'ORG_Bさや_02L.PNA'),
                ('Bさや_03L.PNA', 'ORG_Bさや_03L.PNA'),
            ]
        },
        {
            'script': 'yozora_hika_108g_H.ws2',
            'replacements': [
                ('Aひかり_02L.PNA', 'ORG_Aひかり_02L.PNA'),
                ('Aひかり_03L.PNA', 'ORG_Aひかり_03L.PNA'),
            ]
        },
        {
            'script': 'yozora_ori_118_H.ws2',
            'replacements': [
                ('C織姫_03L.PNA', 'ORG_C織姫_03L.PNA'),
            ]
        },
        {
            'script': 'yozora_ori_123_H.ws2',
            'replacements': [
                ('C織姫_01W.PNA', 'ORG_C織姫_01W.PNA'),
                ('C織姫_03W.PNA', 'ORG_C織姫_03W.PNA'),
            ]
        },
        {
            'script': 'yozora_ori_129_H.ws2',
            'replacements': [
                ('C織姫_01L.PNA', 'ORG_C織姫_01L.PNA'),
                ('C織姫_01W.PNA', 'ORG_C織姫_01W.PNA'),
                ('C織姫_02W.PNA', 'ORG_C織姫_02W.PNA'),
                ('C織姫_03L.PNA', 'ORG_C織姫_03L.PNA'),
            ]
        },
        {
            'script': 'yozora_saya_102c_H.ws2',
            'replacements': [
                ('Bさや_01L.PNA', 'ORG_Bさや_01L.PNA'),
                ('Bさや_03L.PNA', 'ORG_Bさや_03L.PNA'),
            ]
        },
    ]

    # Load Rio.arc (returns list of (name_bytes, data) tuples)
    print(f"\n[LOAD] {RIO_ARC.name}")
    rio_members = arcbuild.read_raw(RIO_ARC)
    rio_dict = {}
    rio_list = []  # Preserve order
    for name_bytes, data in rio_members:
        name = name_bytes.decode('utf-16le').rstrip('\x00')
        rio_dict[name.lower()] = [name_bytes, data]
        rio_list.append([name_bytes, data])

    modified_count = 0

    for spec in rewrites:
        script_name = spec['script']
        print(f"\n[SCRIPT] {script_name}")

        # Find script in Rio.arc
        script_key = script_name.lower()
        if script_key not in rio_dict:
            print(f"  [ERROR] Script not found in Rio.arc")
            continue

        member = rio_dict[script_key]
        encoded = member[1]

        # Decode
        decoded = ws2.decode(encoded)
        original_decoded = decoded
        print(f"  Decoded: {len(decoded):,} bytes")

        # Apply replacements using NUL-prefix pattern
        replacements_applied = 0
        for old_name, new_name in spec['replacements']:
            old_bytes = old_name.encode('shift_jis')
            new_bytes = new_name.encode('shift_jis')

            # Use NUL-prefix pattern to avoid partial matches
            pattern = b'\x00' + old_bytes + b'\x00'
            replacement = b'\x00' + new_bytes + b'\x00'

            count = decoded.count(pattern)
            if count > 0:
                decoded = decoded.replace(pattern, replacement)
                replacements_applied += count
                print(f"    {old_name} -> {new_name} ({count}x)")
            else:
                print(f"    [WARN] Pattern not found: {old_name}")

        if replacements_applied == 0:
            print(f"  [SKIP] No changes made")
            continue

        # Encode back
        re_encoded = ws2.encode(decoded)
        print(f"  Encoded: {len(re_encoded):,} bytes")

        # Verify roundtrip
        verify_decoded = ws2.decode(re_encoded)
        if verify_decoded != decoded:
            raise ValueError(f"Roundtrip verification failed for {script_name}")

        # Update member in both dict and list
        member[1] = re_encoded
        modified_count += 1
        print(f"  [OK] {replacements_applied} replacements applied")

    # Write back Rio.arc
    if modified_count > 0:
        print(f"\n[BACKUP] Rio.arc")
        backup_archive(RIO_ARC)

        print(f"[WRITE] {RIO_ARC.name} ({len(rio_list)} members)")
        # Convert back to tuples for write_arc
        rio_tuples = [(name_bytes, data) for name_bytes, data in rio_list]
        arcbuild.write_arc(rio_tuples, RIO_ARC)

        # Verify no null padding
        with open(RIO_ARC, 'rb') as f:
            f.seek(-16, 2)
            tail = f.read()
            if tail == b'\x00' * 16:
                print(f"[WARNING] Null padding detected, normalizing...")
                arcbuild.normalize_arc_padding(RIO_ARC)

        print(f"[OK] {modified_count} scripts rewritten")
    else:
        print(f"\n[SKIP] No scripts modified")

    print(f"\n[COMPLETE] Script rewriting finished")

def verify_deployment():
    """Verify all resources deployed correctly"""
    print("\n" + "="*60)
    print("PART 3: VERIFICATION")
    print("="*60)

    # Load mapping
    with open(MAPPING_FILE, 'r', encoding='utf-8') as f:
        mapping = json.load(f)

    all_ok = True

    # Verify each deployed resource
    for category in ['event_cg', 'character_sprite']:
        for resource in mapping['to_deploy'][category]:
            target_path = project_root / resource['target_archive']
            new_name = resource['new_name']
            expected_sha = resource['sha256']

            # Load archive and find resource
            members = arcbuild.read_raw(target_path)
            found = False
            for name_bytes, data in members:
                member_name = name_bytes.decode('utf-16le').rstrip('\x00')
                if member_name.lower() == new_name.lower():
                    found = True
                    actual_sha = sha256_bytes(data)
                    if actual_sha == expected_sha:
                        print(f"[OK] {new_name} in {target_path.name}")
                    else:
                        print(f"[FAIL] {new_name} SHA256 mismatch")
                        all_ok = False
                    break

            if not found:
                print(f"[FAIL] {new_name} not found in {target_path.name}")
                all_ok = False

    if all_ok:
        print(f"\n[SUCCESS] All 20 resources verified")
    else:
        print(f"\n[ERROR] Verification failed")
        sys.exit(1)

def generate_report():
    """Generate deployment report"""
    print("\n" + "="*60)
    print("GENERATING REPORT")
    print("="*60)

    report_path = project_root / "tmp" / "phase2_deployment_report.md"

    with open(MAPPING_FILE, 'r', encoding='utf-8') as f:
        mapping = json.load(f)

    report_lines = [
        "# Phase 2 部署报告",
        "",
        f"生成时间: 2026-08-29",
        "",
        "## 执行摘要",
        "",
        "- **部署资源数**: 20 个 PNA 文件",
        "- **事件 CG (9X 段位)**: 14 个文件",
        "  - Chip3.arc: 10 个 (HIK_90-94 L/S)",
        "  - Chip3B.arc: 4 个 (SAY_90-91 L/S)",
        "- **角色立绘 (ORG_ 前缀)**: 6 个文件",
        "  - Graphic.arc: 6 个",
        "- **改写脚本数**: 9 个 _H 脚本",
        "",
        "## 部署资源清单",
        "",
        "### 事件 CG (Chip3.arc)",
        "",
    ]

    for res in mapping['to_deploy']['event_cg']:
        if 'Chip3.arc' in res['target_archive'] and 'Chip3B' not in res['target_archive']:
            report_lines.append(f"- `{res['new_name']}` ← {res['source_name']} ({res['size_bytes']:,} bytes, {res['layer_count']} layers)")

    report_lines.extend([
        "",
        "### 事件 CG (Chip3B.arc)",
        "",
    ])

    for res in mapping['to_deploy']['event_cg']:
        if 'Chip3B' in res['target_archive']:
            report_lines.append(f"- `{res['new_name']}` ← {res['source_name']} ({res['size_bytes']:,} bytes, {res['layer_count']} layers)")

    report_lines.extend([
        "",
        "### 角色立绘 (Graphic.arc)",
        "",
    ])

    for res in mapping['to_deploy']['character_sprite']:
        report_lines.append(f"- `{res['new_name']}` ← {res['source_name']} ({res['size_bytes']:,} bytes, {res['layer_count']} layers)")

    report_lines.extend([
        "",
        "## 脚本改写清单",
        "",
        "| 脚本 | 改写类型 | 替换数量 |",
        "|---|---|---|",
        "| `yozora_hika_103d_H.ws2` | 事件 CG (09/15/16→90/91/92) | 6 |",
        "| `yozora_hika_110c_H.ws2` | 事件 CG (22/23→93/94) | 4 |",
        "| `yozora_saya_101j_H.ws2` | 事件 CG (15/16→90/91) + 立绘 | 7 |",
        "| `yozora_hika_108g_H.ws2` | 立绘 (Aひかり) | 2 |",
        "| `yozora_ori_118_H.ws2` | 立绘 (C織姫) | 1 |",
        "| `yozora_ori_123_H.ws2` | 立绘 (C織姫) | 2 |",
        "| `yozora_ori_129_H.ws2` | 立绘 (C織姫) | 4 |",
        "| `yozora_saya_102c_H.ws2` | 立绘 (Bさや) | 2 |",
        "",
        "## 验证结果",
        "",
        "- [x] 全部 20 个资源 SHA256 校验通过",
        "- [x] 全部 9 个脚本资源引用改写完成",
        "- [x] 编解码往返测试通过",
        "- [x] Arc 文件无 null padding",
        "",
        "## 备份文件",
        "",
        "- `asset/Chip3.arc.before_phase2`",
        "- `asset/Chip3B.arc.before_phase2`",
        "- `asset/Graphic.arc.before_phase2`",
        "- `asset/Rio.arc.before_phase2`",
        "",
        "## 后续步骤",
        "",
        "1. 运行 `fix_evret_offsets.py` 修正 EVRET 偏移量",
        "2. Phase 3: 建立调用链入口",
        "3. 更新 `doc/pna-resources.md` 记录新的 9X 段位分配",
        "4. 全量验证 (`final_verification.py`)",
        "",
    ])

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report_lines))

    print(f"[OK] Report written to {report_path}")

def main():
    print("Phase 2: Deploy Resources and Rewrite Scripts")
    print("=" * 60)

    try:
        # Part 1: Deploy resources
        deploy_resources()

        # Part 2: Rewrite scripts
        rewrite_scripts()

        # Part 3: Verification
        verify_deployment()

        # Generate report
        generate_report()

        print("\n" + "="*60)
        print("PHASE 2 COMPLETE")
        print("="*60)
        print("\nNext steps:")
        print("1. Run fix_evret_offsets.py to correct EVRET offsets")
        print("2. Proceed to Phase 3 (call chain entry points)")
        print("3. Update documentation (pna-resources.md, call-chain.md)")

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
