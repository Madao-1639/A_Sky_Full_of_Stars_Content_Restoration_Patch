#!/bin/bash
# 从项目根目录执行
# bash script/pack.sh

# 读取唯一版本号来源
VERSION=$(cat VERSION)

# 输出目录
RELEASE_DIR=releases
mkdir -p "$RELEASE_DIR"

# 清理旧的构建缓存
rm -rf build *.spec

# 使用 mamba 环境执行 PyInstaller 打包
mamba run -n asky_patch pyinstaller \
    --onefile \
    --add-data "tool/arcbuild.py;." \
    --add-data "payload;payload" \
    --add-data "VERSION;." \
    --add-data "script/icon.ico;." \
    --icon "script/icon.ico" \
    --name "A_Sky_Full_of_Stars_Content_Restoration_Patch_Installer_${VERSION}" \
    --distpath "${RELEASE_DIR}" \
    --clean \
    tool/install.py