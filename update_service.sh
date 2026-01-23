#!/bin/bash
# GRVT Balance Poll Service Update Script
# 用于安全更新服务文件，自动清除缓存并重启服务
# Usage: sudo ./update_service.sh [Python文件路径] [.env文件路径]

set -e

SERVICE_NAME="grvt-balance-poll"
INSTALL_DIR="/opt/grvt-balance-poll"
SERVICE_USER="grvt"
SERVICE_FILE="grvt_balance_poll.py"
ENV_FILE=".env"

echo "=========================================="
echo "GRVT Balance Poll Service Update"
echo "=========================================="

# 检查是否以 root 运行
if [ "$EUID" -ne 0 ]; then 
    echo "❌ 错误: 请使用 sudo 运行此脚本"
    exit 1
fi

# 检查服务是否存在
if ! systemctl list-units --type=service | grep -q "$SERVICE_NAME"; then
    echo "❌ 错误: 服务 $SERVICE_NAME 未安装"
    exit 1
fi

# 检查安装目录是否存在
if [ ! -d "$INSTALL_DIR" ]; then
    echo "❌ 错误: 安装目录不存在: $INSTALL_DIR"
    exit 1
fi

# 解析命令行参数
SOURCE_FILE="$1"
SOURCE_ENV_FILE="$2"

# 如果没有提供参数，提示用户
if [ -z "$SOURCE_FILE" ] && [ -z "$SOURCE_ENV_FILE" ]; then
    echo ""
    echo "用法: sudo ./update_service.sh [Python文件路径] [.env文件路径]"
    echo "  示例: sudo ./update_service.sh ./grvt_balance_poll.py ./env"
    echo "  示例: sudo ./update_service.sh ./grvt_balance_poll.py"
    echo "  示例: sudo ./update_service.sh '' ./env"
    echo ""
    if [ -z "$SOURCE_FILE" ]; then
        read -p "Python 文件路径（留空跳过）: " SOURCE_FILE
    fi
    if [ -z "$SOURCE_ENV_FILE" ]; then
        read -p ".env 文件路径（留空跳过）: " SOURCE_ENV_FILE
    fi
fi

# 步骤 1: 停止服务
echo ""
echo "📋 步骤 1/6: 停止服务..."
if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "正在停止服务..."
    systemctl stop "$SERVICE_NAME"
    echo "等待进程完全终止..."
    sleep 3  # 等待进程完全终止，避免 Restart=always 立即重启
    
    # 检查服务是否真的停止了
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        echo "⚠️  警告: 服务仍在运行，强制等待..."
        sleep 2
    fi
    echo "✓ 服务已停止"
else
    echo "✓ 服务已处于停止状态"
fi

# 步骤 2: 清除 Python 缓存
echo ""
echo "📋 步骤 2/6: 清除 Python 字节码缓存..."
CACHE_COUNT=0

# 清除 __pycache__ 目录
if find "$INSTALL_DIR" -type d -name __pycache__ 2>/dev/null | grep -q .; then
    CACHE_DIRS=$(find "$INSTALL_DIR" -type d -name __pycache__ 2>/dev/null | wc -l)
    find "$INSTALL_DIR" -type d -name __pycache__ -exec rm -r {} + 2>/dev/null || true
    echo "  清除了 $CACHE_DIRS 个 __pycache__ 目录"
    CACHE_COUNT=$((CACHE_COUNT + CACHE_DIRS))
fi

# 清除 .pyc 文件
if find "$INSTALL_DIR" -name "*.pyc" 2>/dev/null | grep -q .; then
    PYC_FILES=$(find "$INSTALL_DIR" -name "*.pyc" 2>/dev/null | wc -l)
    find "$INSTALL_DIR" -name "*.pyc" -delete 2>/dev/null || true
    echo "  清除了 $PYC_FILES 个 .pyc 文件"
    CACHE_COUNT=$((CACHE_COUNT + PYC_FILES))
fi

if [ $CACHE_COUNT -eq 0 ]; then
    echo "  ✓ 未发现缓存文件"
else
    echo "✓ 缓存清除完成（共清除 $CACHE_COUNT 项）"
fi

# 步骤 3: 备份当前版本
echo ""
echo "📋 步骤 3/7: 备份当前版本..."
BACKUP_COUNT=0

# 备份 Python 文件
if [ -f "$INSTALL_DIR/$SERVICE_FILE" ]; then
    BACKUP_FILE="${SERVICE_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
    cp "$INSTALL_DIR/$SERVICE_FILE" "$INSTALL_DIR/$BACKUP_FILE"
    echo "✓ Python 文件已备份到: $BACKUP_FILE"
    BACKUP_COUNT=$((BACKUP_COUNT + 1))
fi

# 备份 .env 文件（如果存在且要更新）
if [ -n "$SOURCE_ENV_FILE" ] && [ -f "$INSTALL_DIR/$ENV_FILE" ]; then
    ENV_BACKUP_FILE="${ENV_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
    cp "$INSTALL_DIR/$ENV_FILE" "$INSTALL_DIR/$ENV_BACKUP_FILE"
    echo "✓ .env 文件已备份到: $ENV_BACKUP_FILE"
    BACKUP_COUNT=$((BACKUP_COUNT + 1))
fi

if [ $BACKUP_COUNT -eq 0 ]; then
    echo "ℹ️  无需备份的文件"
fi

# 步骤 4: 更新 Python 文件（如果提供了源文件）
if [ -n "$SOURCE_FILE" ] && [ -f "$SOURCE_FILE" ]; then
    echo ""
    echo "📋 步骤 4/7: 更新 Python 文件..."
    
    # 检查源文件是否与目标文件相同
    if [ "$SOURCE_FILE" = "$INSTALL_DIR/$SERVICE_FILE" ]; then
        echo "⚠️  警告: 源文件与目标文件相同，跳过复制"
    else
        echo "  从 $SOURCE_FILE 复制到 $INSTALL_DIR/$SERVICE_FILE"
        cp "$SOURCE_FILE" "$INSTALL_DIR/$SERVICE_FILE"
        echo "✓ Python 文件更新完成"
    fi
elif [ -n "$SOURCE_FILE" ]; then
    echo ""
    echo "⚠️  警告: Python 源文件不存在: $SOURCE_FILE"
    echo "  跳过 Python 文件更新"
else
    echo ""
    echo "ℹ️  未提供 Python 文件，跳过更新"
fi

# 步骤 5: 更新 .env 文件（如果提供了源文件）
if [ -n "$SOURCE_ENV_FILE" ] && [ -f "$SOURCE_ENV_FILE" ]; then
    echo ""
    echo "📋 步骤 5/7: 更新 .env 文件..."
    
    # 检查源文件是否与目标文件相同
    if [ "$SOURCE_ENV_FILE" = "$INSTALL_DIR/$ENV_FILE" ]; then
        echo "⚠️  警告: 源文件与目标文件相同，跳过复制"
    else
        echo "  从 $SOURCE_ENV_FILE 复制到 $INSTALL_DIR/$ENV_FILE"
        cp "$SOURCE_ENV_FILE" "$INSTALL_DIR/$ENV_FILE"
        echo "✓ .env 文件更新完成"
    fi
elif [ -n "$SOURCE_ENV_FILE" ]; then
    echo ""
    echo "⚠️  警告: .env 源文件不存在: $SOURCE_ENV_FILE"
    echo "  跳过 .env 文件更新"
else
    echo ""
    echo "ℹ️  未提供 .env 文件，跳过更新"
fi

# 步骤 6: 设置权限
echo ""
echo "📋 步骤 6/7: 设置文件权限..."
if [ -f "$INSTALL_DIR/$SERVICE_FILE" ]; then
    chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/$SERVICE_FILE"
    chmod 644 "$INSTALL_DIR/$SERVICE_FILE"
    echo "✓ Python 文件权限设置完成"
fi

if [ -f "$INSTALL_DIR/$ENV_FILE" ]; then
    chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/$ENV_FILE"
    chmod 600 "$INSTALL_DIR/$ENV_FILE"
    echo "✓ .env 文件权限设置完成（600，仅所有者可读写）"
fi

# 步骤 7: 重启服务
echo ""
echo "📋 步骤 7/7: 重启服务..."
systemctl start "$SERVICE_NAME"
sleep 2  # 等待服务启动

# 检查服务状态
if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "✓ 服务启动成功"
else
    echo "❌ 错误: 服务启动失败"
    echo ""
    echo "查看错误信息："
    systemctl status "$SERVICE_NAME" --no-pager -l
    exit 1
fi

# 显示服务状态
echo ""
echo "=========================================="
echo "更新完成！"
echo "=========================================="
echo ""
echo "服务状态："
systemctl status "$SERVICE_NAME" --no-pager -l | head -n 10
echo ""
echo "查看实时日志："
echo "  sudo journalctl -u $SERVICE_NAME -f"
echo ""
echo "查看文件日志："
echo "  tail -f $INSTALL_DIR/logs/grvt_balance_poll.log"
echo ""
