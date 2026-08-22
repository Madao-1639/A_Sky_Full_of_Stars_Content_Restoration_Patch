#!/usr/bin/env python3
"""
満天の星 内容还原补丁安装器 v1.0.0-beta
A Sky Full of Stars - Content Restoration Patch Installer

安装说明：
1. 运行安装器，自动检测游戏路径
2. 或手动选择游戏根目录（包含 AdvHD.exe）
3. 确认安装

Installation:
1. Run the installer to auto-detect game path
2. Or manually select the game root directory (contains AdvHD.exe)
3. Confirm installation
"""

import sys
import shutil
from pathlib import Path
import arcbuild

def get_version():
    packed = Path(__file__).resolve().parent / 'VERSION'
    if packed.exists():
        return packed.read_text(encoding='utf-8').strip()
    dev = Path(__file__).resolve().parent.parent.parent / 'VERSION'
    return dev.read_text(encoding='utf-8').strip()

CURRENT_VERSION = get_version()

def parse_vdf(vdf_path):
    """
    解析 Steam libraryfolders.vdf 文件
    VDF 格式类似 JSON，使用递归下降解析

    Returns:
        list: [(library_path, {appid: size, ...}), ...]
    """
    try:
        with open(vdf_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except:
        return []

    def tokenize(text):
        """将 VDF 文本分词"""
        tokens = []
        i = 0
        while i < len(text):
            # 跳过空白
            if text[i].isspace():
                i += 1
                continue
            # 字符串（带引号）
            if text[i] == '"':
                i += 1
                start = i
                while i < len(text) and text[i] != '"':
                    if text[i] == '\\' and i + 1 < len(text):
                        i += 2  # 跳过转义字符
                    else:
                        i += 1
                tokens.append(('STRING', text[start:i]))
                i += 1  # 跳过结束引号
            # 左大括号
            elif text[i] == '{':
                tokens.append(('LBRACE', '{'))
                i += 1
            # 右大括号
            elif text[i] == '}':
                tokens.append(('RBRACE', '}'))
                i += 1
            # 注释（// 开头的行）
            elif text[i:i+2] == '//':
                while i < len(text) and text[i] != '\n':
                    i += 1
            else:
                i += 1
        return tokens

    def parse_dict(tokens, pos):
        """解析字典结构"""
        result = {}
        while pos < len(tokens):
            token_type, token_value = tokens[pos]

            if token_type == 'RBRACE':
                # 字典结束
                return result, pos + 1
            elif token_type == 'STRING':
                # key
                key = token_value
                pos += 1

                if pos >= len(tokens):
                    break

                next_type, next_value = tokens[pos]

                if next_type == 'LBRACE':
                    # key { ... } 嵌套字典
                    pos += 1
                    value, pos = parse_dict(tokens, pos)
                    result[key] = value
                elif next_type == 'STRING':
                    # key "value" 键值对
                    result[key] = next_value
                    pos += 1
                else:
                    pos += 1
            else:
                pos += 1

        return result, pos

    # 分词
    tokens = tokenize(content)

    # 解析
    data, _ = parse_dict(tokens, 0)

    # 提取库信息
    libraries = []

    if 'libraryfolders' not in data:
        return []

    libraryfolders = data['libraryfolders']

    for key, value in libraryfolders.items():
        if not isinstance(value, dict):
            continue

        if 'path' not in value or 'apps' not in value:
            continue

        library_path = value['path'].replace('\\\\', '\\')
        apps = value['apps'] if isinstance(value['apps'], dict) else {}

        libraries.append((library_path, apps))

    return libraries


def find_steam_game_path():
    """
    自动检测 Steam 游戏路径（仅 Windows）

    Returns:
        Path or None: 游戏路径，如果找不到则返回 None
    """
    if sys.platform != 'win32':
        return None

    try:
        import winreg

        # 读取 Steam 安装路径
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
        steam_path, _ = winreg.QueryValueEx(key, "SteamPath")
        winreg.CloseKey(key)

        steam_path = Path(steam_path)
        libraryfolders_vdf = steam_path / "steamapps" / "libraryfolders.vdf"

        if not libraryfolders_vdf.exists():
            return None

        # 解析 libraryfolders.vdf
        libraries = parse_vdf(libraryfolders_vdf)

        # 查找 appid 745960（A Sky Full of Stars）
        TARGET_APPID = "745960"

        for library_path, apps in libraries:
            if TARGET_APPID in apps:
                # 构建完整游戏路径
                game_path = Path(library_path) / "steamapps" / "common" / "A Sky Full of Stars"

                # 验证游戏可执行文件是否存在
                if (game_path / "AdvHD.exe").exists():
                    return game_path

        return None

    except Exception as e:
        print(f"自动检测失败: {e}")
        return None


def merge_arc(game_arc_path, patch_arc_path, output_path, metadata_path=None, asset_name=None):
    """
    合并游戏原有的 arc 文件和补丁 arc 文件（资源级替换，按元数据指定的顺序）

    Args:
        game_arc_path: 游戏原有的 arc 文件路径
        patch_arc_path: 补丁 arc 文件路径
        output_path: 输出文件路径
        metadata_path: 元数据文件路径（JSON，包含成员顺序和变化信息）
        asset_name: asset 文件名（如 'Chip3.arc'，用于查找元数据中对应的条目）
    """
    import json

    # 读取游戏原文件
    game_members = {nb.decode('utf-16le'): (nb, d)
                    for nb, d in arcbuild.read_raw(str(game_arc_path))}

    # 读取补丁文件
    patch_members = {nb.decode('utf-16le'): (nb, d)
                     for nb, d in arcbuild.read_raw(str(patch_arc_path))}

    # 读取元数据
    metadata = {}
    if metadata_path and Path(metadata_path).exists() and asset_name:
        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                all_metadata = json.load(f)
            metadata = all_metadata.get(asset_name, {})
        except Exception as e:
            print(f"    警告：无法读取元数据 {metadata_path}: {e}")

    # 使用元数据中的成员顺序和变化信息进行合并
    merged = []
    target_members = metadata.get('members', [])
    deleted_count = len(metadata.get('deleted', []))

    if target_members:
        # 按元数据中的目标顺序重组
        # target_members 中的每个元素是 {"name": "...", "type": "keep|added|modified"}
        missing_members = []
        for member_info in target_members:
            if isinstance(member_info, dict):
                name = member_info.get('name')
                member_type = member_info.get('type', 'keep')
            else:
                # 兼容旧格式（直接是字符串）
                name = member_info
                member_type = 'keep'

            if not name:
                continue

            # 根据类型处理
            if member_type in ('added', 'modified'):
                # 新增或修改：优先用补丁版本，找不到则降级用原版
                if name in patch_members:
                    patch_name_bytes, patch_data = patch_members[name]
                    merged.append((patch_name_bytes, patch_data))
                elif name in game_members:
                    # 补丁中找不到，降级使用原版
                    name_bytes, data = game_members[name]
                    merged.append((name_bytes, data))
                    missing_members.append((name, member_type, 'patch'))
                else:
                    # 都找不到，记录错误
                    missing_members.append((name, member_type, 'both'))
            else:  # 'keep'
                # 保持原版：优先用原版，找不到则用补丁版本
                if name in game_members:
                    name_bytes, data = game_members[name]
                    merged.append((name_bytes, data))
                elif name in patch_members:
                    # 原版中找不到，降级使用补丁版本
                    patch_name_bytes, patch_data = patch_members[name]
                    merged.append((patch_name_bytes, patch_data))
                    missing_members.append((name, member_type, 'game'))
                else:
                    # 都找不到，记录错误
                    missing_members.append((name, member_type, 'both'))

        # 报告缺失成员
        if missing_members:
            print(f"    警告：{len(missing_members)} 个成员未能在预期位置找到")
            for name, mtype, missing_from in missing_members:
                print(f"      - {name} (type={mtype}): {missing_from} 中不存在")
    else:
        # 降级方案：如果没有元数据，按游戏原顺序处理
        for name_bytes, data in arcbuild.read_raw(str(game_arc_path)):
            name = name_bytes.decode('utf-16le')
            if name in patch_members:
                patch_name_bytes, patch_data = patch_members[name]
                merged.append((patch_name_bytes, patch_data))
            else:
                merged.append((name_bytes, data))

        # 追加新增成员
        for name, (name_bytes, data) in patch_members.items():
            if name not in game_members:
                merged.append((name_bytes, data))

    # 写入输出文件
    arcbuild.write_arc(merged, str(output_path))

    return len(game_members), len(patch_members), deleted_count, len(merged)


def select_game_directory():
    """
    选择游戏目录

    Returns:
        Path or None: 游戏路径
    """
    print("=" * 60)
    print(f"仰望夜空的星辰 内容还原补丁 {CURRENT_VERSION}")
    print("A Sky Full of Stars - Content Restoration Patch")
    print("=" * 60)
    print()

    # 尝试自动检测
    print("正在检测游戏路径...")
    print("Detecting game path...")
    print()

    auto_path = find_steam_game_path()

    if auto_path:
        print(f"✓ 检测到游戏路径：")
        print(f"  {auto_path}")
        print()
        use_auto = input("使用此路径? (Y/n): ").strip().lower()
        if use_auto not in ['n', 'no']:
            return auto_path
        print()
    else:
        print("⚠ 未能自动检测到游戏路径")
        print()

    # 手动输入路径
    print("请输入游戏根目录路径（包含 AdvHD.exe 的目录）：")
    print("Please enter the game root directory path (contains AdvHD.exe):")
    print()
    print("提示：")
    print("  1. 直接输入路径（如 E:\\SteamLibrary\\steamapps\\common\\A Sky Full of Stars）")
    print("  2. 输入 '.' 使用安装器所在目录")
    print("  3. 留空取消安装")
    print()

    user_input = input("路径 / Path: ").strip()

    if not user_input:
        return None

    if user_input == '.':
        return Path.cwd()

    # 去除引号（如果用户复制粘贴带引号的路径）
    user_input = user_input.strip('"').strip("'")

    game_path = Path(user_input)

    if not game_path.exists():
        print(f"错误：路径不存在 / Path does not exist: {game_path}")
        return None

    if not (game_path / "AdvHD.exe").exists():
        print(f"错误：该目录下未找到 AdvHD.exe")
        print(f"Error: AdvHD.exe not found in this directory")
        return None

    return game_path


def install():
    """执行安装"""

    # 选择游戏目录
    game_path = select_game_directory()

    if not game_path:
        print("安装已取消")
        print("Installation cancelled")
        return False

    print()
    print("=" * 60)
    print(f"游戏目录: {game_path}")
    print("=" * 60)
    print()

    # 检测 payload 目录
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后
        base_dir = Path(sys._MEIPASS)
    else:
        # 开发时
        base_dir = Path(__file__).resolve().parent.parent
    payload_dir = base_dir / "payload"

    if not payload_dir.exists():
        print(f"错误：找不到 payload 目录")
        print(f"Error: payload directory not found")
        print(f"预期位置：{payload_dir}")
        return False

    print("✓ 检测到补丁文件")
    print()

    # 定义需要处理的文件
    files_to_process = [
        {
            "name": "Rio.arc (主脚本)",
            "game_path": game_path / "Rio.arc",
            "patch_path": payload_dir / "Rio.arc",
            "output_path": game_path / "Rio.arc",
            "requires_merge": False,  # 直接覆盖
        },
        {
            "name": "zh-CN/Rio.arc (中文文本)",
            "game_path": game_path / "zh-CN" / "Rio.arc",
            "patch_path": payload_dir / "zh-CN" / "Rio.arc",
            "output_path": game_path / "zh-CN" / "Rio.arc",
            "requires_merge": False,  # 直接覆盖
        },
        {
            "name": "Chip1.arc (CG 资源)",
            "game_path": game_path / "Chip1.arc",
            "patch_path": payload_dir / "Chip1_patch.arc",
            "output_path": game_path / "Chip1.arc",
            "requires_merge": True,  # 需要合并
        },
        {
            "name": "Chip1A.arc (CG 资源)",
            "game_path": game_path / "Chip1A.arc",
            "patch_path": payload_dir / "Chip1A_patch.arc",
            "output_path": game_path / "Chip1A.arc",
            "requires_merge": True,  # 需要合并
        },
        {
            "name": "Chip2.arc (CG 资源)",
            "game_path": game_path / "Chip2.arc",
            "patch_path": payload_dir / "Chip2_patch.arc",
            "output_path": game_path / "Chip2.arc",
            "requires_merge": True,  # 需要合并
        },
        {
            "name": "Chip3.arc (CG 资源)",
            "game_path": game_path / "Chip3.arc",
            "patch_path": payload_dir / "Chip3_patch.arc",
            "output_path": game_path / "Chip3.arc",
            "requires_merge": True,  # 需要合并
        },
        {
            "name": "Chip3A.arc (CG 资源)",
            "game_path": game_path / "Chip3A.arc",
            "patch_path": payload_dir / "Chip3A_patch.arc",
            "output_path": game_path / "Chip3A.arc",
            "requires_merge": True,  # 需要合并
        },
        {
            "name": "Chip3B.arc (CG 资源)",
            "game_path": game_path / "Chip3B.arc",
            "patch_path": payload_dir / "Chip3B_patch.arc",
            "output_path": game_path / "Chip3B.arc",
            "requires_merge": True,  # 需要合并
        },
        {
            "name": "Graphic.arc (图形资源)",
            "game_path": game_path / "Graphic.arc",
            "patch_path": payload_dir / "Graphic_patch.arc",
            "output_path": game_path / "Graphic.arc",
            "requires_merge": True,  # 需要合并
        },
        {
            "name": "Voice.arc (语音资源)",
            "game_path": game_path / "Voice.arc",
            "patch_path": payload_dir / "Voice_patch.arc",
            "output_path": game_path / "Voice.arc",
            "requires_merge": True,  # 需要合并
        },
        {
            "name": "Voice1.arc (语音资源)",
            "game_path": game_path / "Voice1.arc",
            "patch_path": payload_dir / "Voice1_patch.arc",
            "output_path": game_path / "Voice1.arc",
            "requires_merge": True,  # 需要合并
        },
    ]

    # 检查补丁文件并标记跳过无需更新的文件
    print("检查补丁文件...")
    files_to_process = [f for f in files_to_process if f["patch_path"].exists() or not f["requires_merge"]]

    for file_info in files_to_process:
        # 如果需要合并但 patch 不存在，标记为跳过
        if file_info["requires_merge"] and not file_info["patch_path"].exists():
            file_info["skip"] = True
            print(f"ℹ {file_info['name']}: 无增量，跳过")
        else:
            file_info["skip"] = False
            # Rio.arc 等必需文件必须存在
            if not file_info["patch_path"].exists():
                print(f"错误：缺失补丁文件 {file_info['patch_path']}")
                print(f"Error: Missing patch file {file_info['patch_path']}")
                return False

            if not file_info["game_path"].exists():
                print(f"错误：游戏文件不存在 {file_info['game_path']}")
                print(f"Error: Game file not found {file_info['game_path']}")
                return False

    print("✓ 所有文件检查通过")
    print()

    # 确认安装
    print("即将安装内容还原补丁，这将修改以下文件：")
    print("About to install the content restoration patch. The following files will be modified:")
    for file_info in files_to_process:
        print(f"  - {file_info['name']}")
    print()
    print("建议：安装前通过 Steam 验证游戏完整性以创建备份")
    print("Recommendation: Verify game integrity via Steam before installation to create a backup")
    print()

    confirm = input("确认安装? (Y/n): ").strip().lower()
    if confirm in ['n', 'no']:
        print("安装已取消")
        print("Installation cancelled")
        return False

    print()
    print("开始安装...")
    print()

    # 执行安装
    try:
        for file_info in files_to_process:
            # 跳过无需更新的文件
            if file_info.get("skip"):
                print(f"跳过 {file_info['name']} (无需更新)")
                print()
                continue

            print(f"处理 {file_info['name']}...")

            if file_info["requires_merge"]:
                # 合并 arc 文件
                metadata_path = payload_dir / "METADATA.json"
                asset_name = file_info["game_path"].name
                game_count, patch_count, deleted_count, merged_count = merge_arc(
                    file_info["game_path"],
                    file_info["patch_path"],
                    file_info["output_path"],
                    metadata_path,
                    asset_name
                )
                print(f"  原文件成员: {game_count}")
                print(f"  补丁成员: {patch_count}")
                print(f"  删除成员: {deleted_count}")
                print(f"  合并后成员: {merged_count}")
            else:
                # 直接覆盖
                shutil.copy(file_info["patch_path"], file_info["output_path"])
                file_size = file_info["output_path"].stat().st_size
                print(f"  已覆盖 ({file_size:,} bytes)")

            print(f"✓ {file_info['name']} 完成")
            print()

        # 验证安装文件
        print("验证安装文件...")
        import hashlib
        import json

        metadata_file = payload_dir / "METADATA.json"
        if metadata_file.exists():
            try:
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)

                all_verified = True
                for asset_name, asset_info in metadata.items():
                    expected_hash = asset_info.get('checksum')

                    # 构建文件路径
                    if asset_name.startswith('zh-CN/'):
                        installed_path = game_path / asset_name
                    else:
                        installed_path = game_path / asset_name

                    if not installed_path.exists():
                        print(f"  ✗ {asset_name}: 文件不存在")
                        all_verified = False
                        continue

                    # 计算哈希
                    file_hash = hashlib.sha256(installed_path.read_bytes()).hexdigest()
                    if file_hash == expected_hash:
                        print(f"  ✓ {asset_name}")
                    else:
                        print(f"  ✗ {asset_name}: 哈希不匹配")
                        print(f"    预期: {expected_hash}")
                        print(f"    实际: {file_hash}")
                        all_verified = False

                if not all_verified:
                    print()
                    print("=" * 60)
                    print("✗ 验证失败：部分文件不正确")
                    print("✗ Verification failed: some files are incorrect")
                    print("=" * 60)
                    print()
                    print("请按以下步骤恢复后重新安装：")
                    print("Please follow these steps to recover and reinstall:")
                    print()
                    print("1. 打开 Steam，找到《仰望夜空的星辰》(A Sky Full of Stars)")
                    print("   Open Steam and find 'A Sky Full of Stars'")
                    print()
                    print("2. 右键点击游戏 → 属性 → 已安装文件 → 校验游戏文件完整性")
                    print("   Right-click game → Properties → Installed Files → Verify integrity")
                    print()
                    print("3. 等待 Steam 完成验证和修复")
                    print("   Wait for Steam to complete verification")
                    print()
                    print("4. 重新运行本安装程序")
                    print("   Run this installer again")
                    return False

            except Exception as e:
                print(f"  警告：无法验证文件: {e}")

        print()
        print("=" * 60)
        print("✓ 安装完成！")
        print("✓ Installation completed!")
        print("=" * 60)
        print()
        print("现在可以启动游戏体验还原内容")
        print("You can now launch the game to experience the restored content")
        print()

        return True

    except Exception as e:
        print()
        print("=" * 60)
        print(f"✗ 安装失败：{e}")
        print(f"✗ Installation failed: {e}")
        print("=" * 60)
        print()
        print("请通过 Steam 验证游戏完整性恢复原始文件")
        print("Please verify game integrity via Steam to restore original files")
        return False


if __name__ == "__main__":
    try:
        success = install()
        input("\n按任意键退出...")
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n安装已取消")
        print("Installation cancelled")
        input("\n按任意键退出...")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n未预期的错误：{e}")
        print(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        input("\n按任意键退出...")
        sys.exit(1)
