#!/bin/bash
# GRVT Balance Poll 一键部署脚本
# 功能：自动安装环境、配置服务、启动服务
# 使用方法: sudo ./deploy.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="/opt/grvt-balance-poll"
SERVICE_NAME="grvt-balance-poll"
SERVICE_USER="grvt"

echo "=========================================="
echo "GRVT Balance Poll 一键部署脚本"
echo "=========================================="
echo ""

# 检查是否以 root 运行
if [ "$EUID" -ne 0 ]; then 
    echo "❌ 错误: 请使用 sudo 运行此脚本"
    echo "   使用方法: sudo ./deploy.sh"
    exit 1
fi

# 步骤 1: 检查系统环境
echo "📋 步骤 1/8: 检查系统环境..."
echo "----------------------------------------"

# 检查 Ubuntu 版本
if [ -f /etc/os-release ]; then
    . /etc/os-release
    if [[ "$ID" != "ubuntu" ]]; then
        echo "⚠️  警告: 此脚本主要针对 Ubuntu 系统，当前系统: $ID"
        read -p "是否继续? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    else
        echo "✓ 系统: Ubuntu $VERSION_ID"
    fi
else
    echo "⚠️  警告: 无法检测系统版本"
fi

# 步骤 2: 更新系统包
echo ""
echo "📦 步骤 2/8: 更新系统包..."
echo "----------------------------------------"
read -p "是否更新系统包? (Y/n): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Nn]$ ]]; then
    echo "正在更新系统包（可能需要几分钟）..."
    apt update
    apt upgrade -y
    echo "✓ 系统包更新完成"
else
    echo "⏭️  跳过系统包更新"
fi

# 步骤 3: 安装 Python 3 和 pip
echo ""
echo "🐍 步骤 3/8: 安装 Python 3 和 pip..."
echo "----------------------------------------"

if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version)
    echo "✓ Python 已安装: $PYTHON_VERSION"
else
    echo "正在安装 Python 3..."
    apt install -y python3 python3-pip python3-venv
    echo "✓ Python 3 安装完成"
fi

if command -v pip3 &> /dev/null; then
    PIP_VERSION=$(pip3 --version | head -n1)
    echo "✓ pip 已安装: $PIP_VERSION"
else
    echo "正在安装 pip3..."
    apt install -y python3-pip
    echo "✓ pip3 安装完成"
fi

# 步骤 4: 安装系统依赖
echo ""
echo "🔧 步骤 4/8: 安装系统依赖..."
echo "----------------------------------------"
echo "正在安装构建工具和系统依赖..."
apt install -y build-essential python3-dev curl wget git
echo "✓ 系统依赖安装完成"

# 步骤 5: 安装 Python 依赖
echo ""
echo "📚 步骤 5/8: 安装 Python 依赖..."
echo "----------------------------------------"

# 检查并安装 Python 依赖
echo "检查 Python 依赖..."

# 检查 grvt-pysdk
if python3 -c "import grvt_pysdk" 2>/dev/null; then
    echo "✓ grvt-pysdk 已安装"
else
    echo "正在安装 grvt-pysdk..."
    if pip3 install grvt-pysdk 2>/dev/null; then
        echo "✓ grvt-pysdk 安装完成"
    elif pip3 install --break-system-packages grvt-pysdk 2>/dev/null; then
        echo "✓ grvt-pysdk 安装完成（使用 --break-system-packages）"
    else
        echo "❌ 错误: grvt-pysdk 安装失败"
        echo "   请手动运行: sudo pip3 install grvt-pysdk"
        exit 1
    fi
fi

# 检查 python-dotenv
if python3 -c "import dotenv" 2>/dev/null; then
    echo "✓ python-dotenv 已安装"
else
    echo "正在安装 python-dotenv..."
    if pip3 install python-dotenv 2>/dev/null; then
        echo "✓ python-dotenv 安装完成"
    elif pip3 install --break-system-packages python-dotenv 2>/dev/null; then
        echo "✓ python-dotenv 安装完成（使用 --break-system-packages）"
    else
        echo "❌ 错误: python-dotenv 安装失败"
        echo "   请手动运行: sudo pip3 install python-dotenv"
        exit 1
    fi
fi

echo "✓ 所有 Python 依赖已就绪"

# 步骤 6: 准备项目目录和文件
echo ""
echo "📁 步骤 6/8: 准备项目目录和文件..."
echo "----------------------------------------"

# 创建安装目录
echo "创建安装目录: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR/logs"

# 检查项目文件是否存在
if [ ! -f "$SCRIPT_DIR/grvt_balance_poll.py" ]; then
    echo "❌ 错误: 未找到 grvt_balance_poll.py 文件"
    echo "   请确保在项目根目录运行此脚本"
    exit 1
fi

# 复制文件
echo "复制项目文件..."
cp "$SCRIPT_DIR/grvt_balance_poll.py" "$INSTALL_DIR/"

# 复制 .env 文件（如果存在）
if [ -f "$SCRIPT_DIR/.env" ]; then
    cp "$SCRIPT_DIR/.env" "$INSTALL_DIR/"
    echo "✓ .env 文件已复制"
else
    echo "⚠️  警告: .env 文件不存在"
    if [ -f "$SCRIPT_DIR/.env.example" ]; then
        cp "$SCRIPT_DIR/.env.example" "$INSTALL_DIR/.env"
        echo "✓ 已从 .env.example 创建 .env 文件"
        echo "⚠️  请务必编辑 $INSTALL_DIR/.env 文件并配置正确的 API 密钥"
    else
        echo "⚠️  请稍后手动创建 $INSTALL_DIR/.env 文件"
    fi
fi

# 复制服务文件
if [ -f "$SCRIPT_DIR/grvt-balance-poll.service" ]; then
    cp "$SCRIPT_DIR/grvt-balance-poll.service" "$INSTALL_DIR/"
    echo "✓ 服务文件已复制"
fi

echo "✓ 项目文件准备完成"

# 步骤 7: 安装 systemd 服务
echo ""
echo "⚙️  步骤 7/8: 安装 systemd 服务..."
echo "----------------------------------------"

# 创建服务用户
if ! id "$SERVICE_USER" &>/dev/null; then
    echo "创建服务用户: $SERVICE_USER"
    useradd -r -s /bin/false -d "$INSTALL_DIR" "$SERVICE_USER"
    echo "✓ 服务用户创建完成"
else
    echo "✓ 服务用户已存在: $SERVICE_USER"
fi

# 设置文件权限
echo "设置文件权限..."
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
chmod 755 "$INSTALL_DIR"
chmod 644 "$INSTALL_DIR/grvt_balance_poll.py"
chmod 600 "$INSTALL_DIR/.env" 2>/dev/null || true
chmod 755 "$INSTALL_DIR/logs"

# 查找 Python3 路径
PYTHON3_PATH=$(which python3)
if [ -z "$PYTHON3_PATH" ]; then
    echo "❌ 错误: 未找到 python3"
    exit 1
fi
echo "使用 Python 路径: $PYTHON3_PATH"

# 安装 systemd 服务文件
if [ -f "$SCRIPT_DIR/grvt-balance-poll.service" ]; then
    SERVICE_FILE="$SCRIPT_DIR/grvt-balance-poll.service"
else
    echo "❌ 错误: 未找到 grvt-balance-poll.service 文件"
    exit 1
fi

echo "安装 systemd 服务文件..."
sed -e "s|/opt/grvt-balance-poll|$INSTALL_DIR|g" \
    -e "s|/usr/bin/python3|$PYTHON3_PATH|g" \
    "$SERVICE_FILE" > "/etc/systemd/system/${SERVICE_NAME}.service"
chmod 644 "/etc/systemd/system/${SERVICE_NAME}.service"

# 重新加载 systemd
echo "重新加载 systemd..."
systemctl daemon-reload

# 启用服务
echo "启用服务（开机自启）..."
systemctl enable "$SERVICE_NAME"
echo "✓ 服务安装完成"

# 步骤 8: 配置和启动服务
echo ""
echo "🚀 步骤 8/8: 配置和启动服务..."
echo "----------------------------------------"

# 检查 .env 文件
if [ ! -f "$INSTALL_DIR/.env" ]; then
    echo "❌ 错误: .env 文件不存在"
    echo "   请创建 $INSTALL_DIR/.env 文件并配置 API 密钥"
    echo "   可以参考 $INSTALL_DIR/.env.example（如果存在）"
    exit 1
fi

# 检查 .env 文件是否已配置（简单检查是否包含 API_KEY）
if ! grep -q "GRVT.*API_KEY.*=" "$INSTALL_DIR/.env" 2>/dev/null; then
    echo "⚠️  警告: .env 文件可能未正确配置"
    echo "   请确保 $INSTALL_DIR/.env 文件包含必要的 API 密钥配置"
    read -p "是否现在编辑 .env 文件? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        ${EDITOR:-nano} "$INSTALL_DIR/.env"
    fi
fi

# 询问是否立即启动服务
echo ""
read -p "是否立即启动服务? (Y/n): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Nn]$ ]]; then
    echo "正在启动服务..."
    systemctl start "$SERVICE_NAME"
    
    # 等待一下让服务启动
    sleep 2
    
    # 检查服务状态
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        echo "✓ 服务启动成功"
    else
        echo "⚠️  警告: 服务可能启动失败"
        echo "   请运行以下命令查看详细错误："
        echo "   sudo systemctl status $SERVICE_NAME"
        echo "   sudo journalctl -u $SERVICE_NAME -n 50"
    fi
else
    echo "⏭️  跳过服务启动"
    echo "   稍后可以手动启动: sudo systemctl start $SERVICE_NAME"
fi

# 显示部署完成信息
echo ""
echo "=========================================="
echo "✅ 部署完成！"
echo "=========================================="
echo ""
echo "📋 部署信息："
echo "   安装目录: $INSTALL_DIR"
echo "   服务名称: $SERVICE_NAME"
echo "   服务用户: $SERVICE_USER"
echo "   日志目录: $INSTALL_DIR/logs"
echo ""
echo "📝 重要提示："
echo "   1. 请确保 $INSTALL_DIR/.env 文件已正确配置"
echo "   2. 服务已设置为开机自启"
echo ""
echo "🔧 服务管理命令："
echo "   启动服务:   sudo systemctl start $SERVICE_NAME"
echo "   停止服务:   sudo systemctl stop $SERVICE_NAME"
echo "   重启服务:   sudo systemctl restart $SERVICE_NAME"
echo "   查看状态:   sudo systemctl status $SERVICE_NAME"
echo "   查看日志:   sudo journalctl -u $SERVICE_NAME -f"
echo "   查看文件日志: tail -f $INSTALL_DIR/logs/grvt_balance_poll.log"
echo ""
echo "📚 更多信息："
echo "   - 详细配置说明: 查看 README.md"
echo "   - 部署指南: 查看 DEPLOYMENT.md"
echo ""
