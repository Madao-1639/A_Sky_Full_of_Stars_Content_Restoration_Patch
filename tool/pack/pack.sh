#!/bin/bash
# 进入打包目录
cd tool/pack || exit

# 清理旧的构建缓存
rm -rf build/ dist/

# 使用 mamba 环境执行 PyInstaller 打包
mamba run -n asky_patch pyinstaller \
    --onefile \
    --add-data "arcbuild.py;." \
    --add-data "payload;payload" \
    --name "A_Sky_Full_of_Stars_Content_Restoration_Patch_Installer_v1.0.0-beta" \
    --clean \
    install.py \
    # --icon=icon.ico # 指定 icon

# 如果不需要 mamba，可替换为直接 pyinstaller 命令