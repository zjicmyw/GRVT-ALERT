#!/bin/bash
# GRVT Balance Poll Service Uninstallation Script
# Usage: sudo ./uninstall_service.sh

set -e

SERVICE_NAME="grvt-balance-poll"
SYSTEMD_DIR="/etc/systemd/system"
INSTALL_DIR="/opt/grvt-balance-poll"
SERVICE_USER="grvt"

echo "=========================================="
echo "GRVT Balance Poll Service Uninstallation"
echo "=========================================="

# 检查是否以 root 运行
if [ "$EUID" -ne 0 ]; then 
    echo "错误: 请使用 sudo 运行此脚本"
    exit 1
fi

# 停止并禁用服务
if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "停止服务..."
    systemctl stop "$SERVICE_NAME"
fi

if systemctl is-enabled --quiet "$SERVICE_NAME"; then
    echo "禁用服务..."
    systemctl disable "$SERVICE_NAME"
fi

# 删除服务文件
if [ -f "$SYSTEMD_DIR/${SERVICE_NAME}.service" ]; then
    echo "删除服务文件..."
    rm "$SYSTEMD_DIR/${SERVICE_NAME}.service"
    systemctl daemon-reload
fi

# 询问是否删除安装目录
read -p "是否删除安装目录 $INSTALL_DIR? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    if [ -d "$INSTALL_DIR" ]; then
        echo "删除安装目录..."
        rm -rf "$INSTALL_DIR"
    fi
fi

# 询问是否删除服务用户
read -p "是否删除服务用户 $SERVICE_USER? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    if id "$SERVICE_USER" &>/dev/null; then
        echo "删除服务用户..."
        userdel "$SERVICE_USER"
    fi
fi

echo ""
echo "=========================================="
echo "卸载完成！"
echo "=========================================="
