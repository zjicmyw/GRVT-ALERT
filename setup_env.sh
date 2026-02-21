#!/bin/bash
# GRVT-ALERT 运行环境设置脚本
# 功能：自动安装 Python 依赖、创建虚拟环境（可选）

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "GRVT-ALERT 运行环境设置"
echo "=========================================="
echo ""

# 检查 Python 版本
echo "📋 检查 Python 环境..."
if ! command -v python3 &> /dev/null; then
    echo "❌ 错误: 未找到 python3"
    echo "   请先安装 Python 3.8 或更高版本"
    exit 1
fi

PYTHON_VERSION=$(python3 --version)
echo "✓ Python 版本: $PYTHON_VERSION"

# 检查 pip
if ! command -v pip3 &> /dev/null; then
    echo "❌ 错误: 未找到 pip3"
    echo "   请先安装 pip"
    exit 1
fi

PIP_VERSION=$(pip3 --version | head -n1)
echo "✓ pip 版本: $PIP_VERSION"
echo ""

# 询问是否使用虚拟环境
USE_VENV=""
read -p "是否使用虚拟环境? (推荐) (Y/n): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Nn]$ ]]; then
    USE_VENV="yes"
fi

# 创建虚拟环境（如果选择）
if [ "$USE_VENV" = "yes" ]; then
    VENV_DIR="$SCRIPT_DIR/venv"
    if [ -d "$VENV_DIR" ]; then
        echo "✓ 虚拟环境已存在: $VENV_DIR"
    else
        echo "📦 创建虚拟环境..."
        python3 -m venv "$VENV_DIR"
        echo "✓ 虚拟环境创建完成"
    fi
    
    echo "🔧 激活虚拟环境..."
    source "$VENV_DIR/bin/activate"
    echo "✓ 虚拟环境已激活"
    echo ""
fi

# 升级 pip
echo "📦 升级 pip..."
pip3 install --upgrade pip --quiet
echo "✓ pip 升级完成"
echo ""

# 安装依赖
echo "📚 安装 Python 依赖..."
if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    pip3 install -r "$SCRIPT_DIR/requirements.txt"
    echo "✓ 依赖安装完成"
else
    echo "⚠️  警告: requirements.txt 文件不存在"
    echo "   手动安装依赖:"
    echo "   pip3 install grvt-pysdk python-dotenv requests eth-account"
    pip3 install grvt-pysdk python-dotenv requests eth-account
    echo "✓ 依赖安装完成"
fi
echo ""

# 检查 .env 文件
echo "📝 检查配置文件..."
if [ -f "$SCRIPT_DIR/.env" ]; then
    echo "✓ .env 文件已存在"
else
    echo "⚠️  警告: .env 文件不存在"
    if [ -f "$SCRIPT_DIR/.env.example" ]; then
        echo "   发现 .env.example 文件，是否复制为 .env? (Y/n): "
        read -p "" -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Nn]$ ]]; then
            cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
            echo "✓ 已从 .env.example 创建 .env 文件"
            echo "⚠️  请务必编辑 .env 文件并配置正确的 API 密钥"
        fi
    else
        echo "   请手动创建 .env 文件并配置必要的环境变量"
    fi
fi
echo ""

# 检查配置文件
if [ -f "$SCRIPT_DIR/config/hedge_symbols.json" ]; then
    echo "✓ hedge_symbols.json 配置文件已存在"
else
    echo "⚠️  警告: config/hedge_symbols.json 文件不存在"
    if [ -f "$SCRIPT_DIR/config/hedge_symbols.example.json" ]; then
        echo "   发现 hedge_symbols.example.json 文件，是否复制? (Y/n): "
        read -p "" -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Nn]$ ]]; then
            cp "$SCRIPT_DIR/config/hedge_symbols.example.json" "$SCRIPT_DIR/config/hedge_symbols.json"
            echo "✓ 已从示例文件创建 hedge_symbols.json"
            echo "⚠️  请务必编辑 config/hedge_symbols.json 文件并配置正确的交易对"
        fi
    fi
fi
echo ""

# 显示完成信息
echo "=========================================="
echo "✅ 运行环境设置完成！"
echo "=========================================="
echo ""

if [ "$USE_VENV" = "yes" ]; then
    echo "📋 重要提示："
    echo "   已创建并激活虚拟环境: $VENV_DIR"
    echo ""
    echo "🔧 使用方法："
    echo "   1. 激活虚拟环境:"
    echo "      source venv/bin/activate"
    echo ""
    echo "   2. 运行脚本:"
    echo "      python3 grvt_balance_poll.py"
    echo "      或"
    echo "      python3 grvt_dual_maker_hedge.py"
    echo ""
    echo "   3. 退出虚拟环境:"
    echo "      deactivate"
else
    echo "🔧 运行脚本:"
    echo "   python3 grvt_balance_poll.py"
    echo "   或"
    echo "   python3 grvt_dual_maker_hedge.py"
fi

echo ""
echo "📝 下一步："
echo "   1. 配置 .env 文件（如果尚未配置）"
echo "   2. 配置 config/hedge_symbols.json（如果使用对冲引擎）"
echo "   3. 运行相应的脚本"
echo ""
