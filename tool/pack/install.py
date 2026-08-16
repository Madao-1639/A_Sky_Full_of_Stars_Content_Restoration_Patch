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

# 检测 Python 版本
if sys.version_info < (3, 7):
    print("错误：需要 Python 3.7 或更高版本")
    print("Error: Python 3.7 or higher is required")
    input("按任意键退出...")
    sys.exit(1)

try:
    # 动态导入 arcbuild（从脚本同目录）
    script_dir = Path(__file__).parent
    payload_dir = script_dir / "payload"

    # 将脚本目录添加到 sys.path 以便导入 arcbuild
    sys.path.insert(0, str(script_dir))
    import arcbuild
except ImportError:
    print("错误：找不到 arcbuild 模块")
    print("Error: arcbuild module not found")
    print(f"请确保 arcbuild.py 在脚本同目录下")
    input("按任意键退出...")
    sys.exit(1)


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


def merge_arc(game_arc_path, patch_arc_path, output_path):
    """
    合并游戏原有的 arc 文件和补丁 arc 文件

    Args:
        game_arc_path: 游戏原有的 arc 文件路径
        patch_arc_path: 补丁 arc 文件路径
        output_path: 输出文件路径
    """
    # 读取游戏原文件
    game_members = {nb.decode('utf-16le'): (nb, d)
                    for nb, d in arcbuild.read_raw(str(game_arc_path))}

    # 读取补丁文件
    patch_members = list(arcbuild.read_raw(str(patch_arc_path)))

    # 合并：补丁成员追加到游戏成员列表
    merged = list(game_members.values()) + patch_members

    # 写入输出文件
    arcbuild.write_arc(merged, str(output_path))

    return len(game_members), len(patch_members), len(merged)


def select_game_directory():
    """
    选择游戏目录

    Returns:
        Path or None: 游戏路径
    """
    print("=" * 60)
    print("仰望夜空的星辰 内容还原补丁 v1.0.0-beta")
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
    script_dir = Path(__file__).parent
    payload_dir = script_dir / "payload"

    if not payload_dir.exists():
        print(f"错误：找不到 payload 目录")
        print(f"Error: payload directory not found")
        print(f"预期位置：{payload_dir}")
        input("按任意键退出...")
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

    # 检查所有补丁文件是否存在
    print("检查补丁文件...")
    for file_info in files_to_process:
        if not file_info["patch_path"].exists():
            print(f"错误：缺失补丁文件 {file_info['patch_path']}")
            print(f"Error: Missing patch file {file_info['patch_path']}")
            input("按任意键退出...")
            return False
        if not file_info["game_path"].exists():
            print(f"错误：游戏文件不存在 {file_info['game_path']}")
            print(f"Error: Game file not found {file_info['game_path']}")
            input("按任意键退出...")
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

    confirm = input("确认安装? (y/N): ").strip().lower()
    if confirm not in ['y', 'yes']:
        print("安装已取消")
        print("Installation cancelled")
        return False

    print()
    print("开始安装...")
    print()

    # 执行安装
    try:
        for file_info in files_to_process:
            print(f"处理 {file_info['name']}...")

            if file_info["requires_merge"]:
                # 合并 arc 文件
                game_count, patch_count, merged_count = merge_arc(
                    file_info["game_path"],
                    file_info["patch_path"],
                    file_info["output_path"]
                )
                print(f"  原文件成员: {game_count}")
                print(f"  补丁成员: {patch_count}")
                print(f"  合并后成员: {merged_count}")
            else:
                # 直接覆盖
                shutil.copy(file_info["patch_path"], file_info["output_path"])
                file_size = file_info["output_path"].stat().st_size
                print(f"  已覆盖 ({file_size:,} bytes)")

            print(f"✓ {file_info['name']} 完成")
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
