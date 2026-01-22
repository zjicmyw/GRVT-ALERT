#!/bin/bash
# GRVT Balance Poll Service Installation Script
# Usage: sudo ./install_service.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="grvt-balance-poll"
SERVICE_FILE="${SERVICE_NAME}.service"
SYSTEMD_DIR="/etc/systemd/system"
INSTALL_DIR="/opt/grvt-balance-poll"
SERVICE_USER="grvt"

echo "=========================================="
echo "GRVT Balance Poll Service Installation"
echo "=========================================="

# 检查是否以 root 运行
if [ "$EUID" -ne 0 ]; then 
    echo "错误: 请使用 sudo 运行此脚本"
    exit 1
fi

# 检查 Python3 是否安装
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到 python3，请先安装 Python 3"
    exit 1
fi

# 创建服务用户（如果不存在）
if ! id "$SERVICE_USER" &>/dev/null; then
    echo "创建服务用户: $SERVICE_USER"
    useradd -r -s /bin/false -d "$INSTALL_DIR" "$SERVICE_USER"
else
    echo "服务用户已存在: $SERVICE_USER"
fi

# 创建安装目录
echo "创建安装目录: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR/logs"

# 复制文件到安装目录
echo "复制文件到 $INSTALL_DIR..."
cp "$SCRIPT_DIR/grvt_balance_poll.py" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/.env" "$INSTALL_DIR/" 2>/dev/null || echo "警告: .env 文件不存在，请稍后手动创建"
cp "$SCRIPT_DIR/.env.example" "$INSTALL_DIR/" 2>/dev/null || echo "提示: .env.example 文件不存在"

# 设置文件权限
echo "设置文件权限..."
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
chmod 755 "$INSTALL_DIR"
chmod 644 "$INSTALL_DIR/grvt_balance_poll.py"
chmod 600 "$INSTALL_DIR/.env" 2>/dev/null || true
chmod 755 "$INSTALL_DIR/logs"

# 安装 systemd 服务文件
echo "安装 systemd 服务文件..."
# 查找 Python3 路径
PYTHON3_PATH=$(which python3)
if [ -z "$PYTHON3_PATH" ]; then
    echo "错误: 未找到 python3，请先安装 Python 3"
    exit 1
fi
echo "使用 Python 路径: $PYTHON3_PATH"

# 更新服务文件中的路径和 Python 路径
sed -e "s|/opt/grvt-balance-poll|$INSTALL_DIR|g" \
    -e "s|/usr/bin/python3|$PYTHON3_PATH|g" \
    -e "s|/bin/sh -c 'python3|/bin/sh -c '$PYTHON3_PATH|g" \
    "$SCRIPT_DIR/$SERVICE_FILE" > "$SYSTEMD_DIR/$SERVICE_FILE"
chmod 644 "$SYSTEMD_DIR/$SERVICE_FILE"

# 检查 Python 依赖
echo "检查 Python 依赖..."
MISSING_DEPS=0
if ! python3 -c "import grvt_pysdk" 2>/dev/null; then
    echo "警告: grvt-pysdk 未安装"
    MISSING_DEPS=1
fi
if ! python3 -c "import dotenv" 2>/dev/null; then
    echo "警告: python-dotenv 未安装"
    MISSING_DEPS=1
fi

if [ $MISSING_DEPS -eq 1 ]; then
    echo ""
    echo "请先安装 Python 依赖："
    echo "  sudo pip3 install grvt-pysdk python-dotenv"
    echo ""
    echo "或者参考完整部署指南: DEPLOYMENT.md"
    echo ""
    read -p "是否现在安装依赖? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "正在安装依赖..."
        pip3 install grvt-pysdk python-dotenv || sudo pip3 install grvt-pysdk python-dotenv
        echo "依赖安装完成"
    else
        echo "请手动安装依赖后再继续"
        exit 1
    fi
fi

# 重新加载 systemd
echo "重新加载 systemd..."
systemctl daemon-reload

# 启用服务（开机自启）
echo "启用服务（开机自启）..."
systemctl enable "$SERVICE_NAME"

echo ""
echo "=========================================="
echo "安装完成！"
echo "=========================================="
echo ""
echo "服务管理命令："
echo "  启动服务:   sudo systemctl start $SERVICE_NAME"
echo "  停止服务:   sudo systemctl stop $SERVICE_NAME"
echo "  重启服务:   sudo systemctl restart $SERVICE_NAME"
echo "  查看状态:   sudo systemctl status $SERVICE_NAME"
echo "  查看日志:   sudo journalctl -u $SERVICE_NAME -f"
echo "  查看文件日志: tail -f $INSTALL_DIR/logs/grvt_balance_poll.log"
echo ""
echo "注意："
echo "  1. 请确保 $INSTALL_DIR/.env 文件已正确配置"
echo "  2. 服务将以用户 '$SERVICE_USER' 运行"
echo "  3. 日志文件位于: $INSTALL_DIR/logs/"
echo ""
