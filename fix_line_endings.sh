#!/bin/bash
# 修复文件行尾符的脚本（在 Linux 服务器上运行）
# 使用方法: bash fix_line_endings.sh

echo "修复文件行尾符..."

# 安装 dos2unix（如果未安装）
if ! command -v dos2unix &> /dev/null; then
    echo "正在安装 dos2unix..."
    sudo apt install -y dos2unix
fi

# 修复所有脚本文件的行尾符
for file in deploy.sh install_service.sh uninstall_service.sh; do
    if [ -f "$file" ]; then
        echo "修复 $file..."
        dos2unix "$file"
        chmod +x "$file"
    fi
done

echo "完成！现在可以运行: sudo ./deploy.sh"
