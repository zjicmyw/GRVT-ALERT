# GRVT Balance Poll 部署指南（Ubuntu）

本文档提供在 Ubuntu 生产环境中从零开始部署 GRVT Balance Poll 服务的完整步骤。

## 快速开始（一键部署）

如果你想要快速部署，可以使用一键部署脚本：

```bash
# 1. 上传项目文件到服务器（使用 scp、rsync 或 Git）
# 例如：
scp -r /path/to/grvt-balance-poll/* user@server:/opt/grvt-balance-poll/

# 2. SSH 登录到服务器
ssh user@server

# 3. 进入项目目录
cd /opt/grvt-balance-poll

# 4. 检查文件是否存在
ls -la deploy.sh

# 5. 修复文件行尾符（如果从 Windows 上传，可能需要）
# 如果系统没有 dos2unix，先安装: sudo apt install -y dos2unix
dos2unix deploy.sh install_service.sh uninstall_service.sh 2>/dev/null || {
    echo "如果出现 'No such file or directory' 错误，请运行："
    echo "  sudo apt install -y dos2unix"
    echo "  dos2unix deploy.sh"
}

# 6. 给脚本执行权限
chmod +x deploy.sh

# 7. 运行一键部署脚本（需要 sudo）
sudo ./deploy.sh
```

**一键部署脚本会自动完成**：
- ✅ 检查系统环境（Ubuntu 版本等）
- ✅ 更新系统包（可选，默认是）
- ✅ 安装 Python 3 和 pip（如果未安装）
- ✅ 安装系统依赖（build-essential, python3-dev 等）
- ✅ 安装 Python 依赖（grvt-pysdk, python-dotenv）
- ✅ 准备项目目录和文件
- ✅ 创建服务用户
- ✅ 安装 systemd 服务
- ✅ 配置并启动服务（可选）

**交互式提示**：
- 是否更新系统包（默认：是）
- 如果 .env 文件未配置，会提示编辑
- 是否立即启动服务（默认：是）

**预期执行时间**：5-10 分钟（取决于网络速度和系统更新）

---

## 手动部署步骤

如果你想手动控制每个步骤，可以按照以下详细步骤操作：

## 前置要求

- Ubuntu 18.04 或更高版本
- 具有 sudo 权限的用户
- 网络连接（用于下载依赖和访问 GRVT API）

## 步骤 1: 检查系统环境

```bash
# 检查 Ubuntu 版本
lsb_release -a

# 检查当前用户权限
whoami
```

## 步骤 2: 更新系统包

```bash
sudo apt update
sudo apt upgrade -y
```

## 步骤 3: 安装 Python 3 和 pip

```bash
# 安装 Python 3 和 pip
sudo apt install -y python3 python3-pip python3-venv

# 验证安装
python3 --version
pip3 --version
```

**预期输出**：
```
Python 3.10.x 或更高版本
pip 23.x.x 或更高版本
```

## 步骤 4: 安装系统依赖

```bash
# 安装构建工具（某些 Python 包可能需要）
sudo apt install -y build-essential python3-dev

# 安装其他可能需要的依赖
sudo apt install -y curl wget git
```

## 步骤 5: 准备项目目录

```bash
# 创建项目目录（如果不存在）
sudo mkdir -p /opt/grvt-balance-poll
sudo chown $USER:$USER /opt/grvt-balance-poll

# 或者使用当前用户目录
# mkdir -p ~/grvt-balance-poll
# cd ~/grvt-balance-poll
```

## 步骤 6: 上传项目文件

将以下文件上传到服务器（使用 `scp`、`rsync` 或 Git）：

**必需文件**：
- `grvt_balance_poll.py` - 主程序文件
- `.env` - 环境配置文件（包含 API 密钥等敏感信息）
- `.env.example` - 环境配置示例文件（可选）
- `grvt-balance-poll.service` - systemd 服务文件
- `install_service.sh` - 服务安装脚本
- `uninstall_service.sh` - 服务卸载脚本（可选）

**上传方法示例**：

```bash
# 方法 1: 使用 scp（从本地 Windows 上传）
# 在 Windows PowerShell 中执行：
scp -r d:\Code\GRVT\* user@your-server-ip:/opt/grvt-balance-poll/

# 方法 2: 使用 Git（如果项目在 Git 仓库中）
cd /opt/grvt-balance-poll
git clone https://your-repo-url.git .
# 注意：需要手动创建 .env 文件，不要提交到 Git

# 方法 3: 使用 rsync
rsync -avz d:\Code\GRVT\ user@your-server-ip:/opt/grvt-balance-poll/
```

## 步骤 7: 配置环境变量

```bash
cd /opt/grvt-balance-poll

# 如果还没有 .env 文件，从示例文件创建
if [ ! -f .env ]; then
    cp .env.example .env
    echo "已创建 .env 文件，请编辑配置"
fi

# 编辑 .env 文件
nano .env
# 或使用 vi
# vi .env
```

**配置示例**（根据实际情况修改）：

```env
# 轮询配置
GRVT_POLL_INTERVAL=30

# 自动余额平衡配置
GRVT_BALANCE_THRESHOLD_PERCENT=43
GRVT_BALANCE_TARGET_PERCENT=48

# Funding Sweep 配置
GRVT_FUNDING_SWEEP_THRESHOLD=100

# 日志级别配置
GRVT_LOG_LEVEL=INFO

# 通知配置
GRVT_DAILY_SUMMARY_TIME=16:30
GRVT_ALERT_DEVICE_KEY=your_bark_device_key_here

# 全局环境变量
GRVT_ENV=prod

# 交易账户 1 配置
GRVT_TRADING_API_KEY_1=your_trading_api_key_1
GRVT_TRADING_PRIVATE_KEY_1=your_trading_private_key_1
GRVT_TRADING_ACCOUNT_ID_1=your_trading_account_id_1
GRVT_RELATED_FUNDING_ACCOUNT_ID_1=your_funding_account_address_1
GRVT_RELATED_MAIN_ACCOUNT_ID_1=your_main_account_id_1

# 资金账户 1 配置
GRVT_FUNDING_API_KEY_1=your_funding_api_key_1
GRVT_FUNDING_PRIVATE_KEY_1=your_funding_private_key_1
GRVT_FUNDING_ACCOUNT_ID_1=your_funding_account_id_1
GRVT_FUNDING_ACCOUNT_ADDRESS_1=0x...
GRVT_RELATED_TRADING_ACCOUNT_ID_1=your_trading_account_id_1
GRVT_RELATED_MAIN_ACCOUNT_ID_1=your_main_account_id_1

# 交易账户 2 配置（如果使用自动平衡功能）
GRVT_TRADING_API_KEY_2=your_trading_api_key_2
GRVT_TRADING_PRIVATE_KEY_2=your_trading_private_key_2
GRVT_TRADING_ACCOUNT_ID_2=your_trading_account_id_2
GRVT_RELATED_FUNDING_ACCOUNT_ID_2=your_funding_account_address_2
GRVT_RELATED_MAIN_ACCOUNT_ID_2=your_main_account_id_2

# 资金账户 2 配置
GRVT_FUNDING_API_KEY_2=your_funding_api_key_2
GRVT_FUNDING_PRIVATE_KEY_2=your_funding_private_key_2
GRVT_FUNDING_ACCOUNT_ID_2=your_funding_account_id_2
GRVT_FUNDING_ACCOUNT_ADDRESS_2=0x...
GRVT_RELATED_TRADING_ACCOUNT_ID_2=your_trading_account_id_2
GRVT_RELATED_MAIN_ACCOUNT_ID_2=your_main_account_id_2
```

**重要**：确保 `.env` 文件权限安全：

```bash
chmod 600 .env
```

## 步骤 8: 安装 Python 依赖

```bash
cd /opt/grvt-balance-poll

# 安装项目依赖
sudo pip3 install grvt-pysdk python-dotenv

# 或者使用用户级安装（推荐，避免系统级污染）
pip3 install --user grvt-pysdk python-dotenv

# 验证安装
python3 -c "import grvt_pysdk; print('grvt-pysdk installed')"
python3 -c "import dotenv; print('python-dotenv installed')"
```

**如果使用用户级安装，需要更新服务文件中的 Python 路径**：

```bash
# 查找 Python 路径
which python3
# 通常为 /usr/bin/python3 或 /usr/local/bin/python3

# 如果使用 --user 安装，可能需要添加到 PATH
# 编辑 ~/.bashrc 或系统级 /etc/environment
```

## 步骤 9: 测试运行（可选但推荐）

在安装为服务之前，先手动测试脚本是否能正常运行：

```bash
cd /opt/grvt-balance-poll

# 手动运行脚本（按 Ctrl+C 停止）
python3 grvt_balance_poll.py
```

**检查要点**：
- 脚本能正常启动
- 能成功连接 GRVT API
- 能正常查询余额
- 日志输出正常

如果测试成功，按 `Ctrl+C` 停止脚本。

## 步骤 10: 安装 systemd 服务

```bash
cd /opt/grvt-balance-poll

# 确保安装脚本有执行权限
chmod +x install_service.sh

# 运行安装脚本（需要 sudo 权限）
sudo ./install_service.sh
```

**安装脚本会执行以下操作**：
1. 创建服务用户 `grvt`
2. 复制文件到 `/opt/grvt-balance-poll`
3. 设置文件权限
4. 安装 systemd 服务文件
5. 启用服务（开机自启）

## 步骤 11: 启动服务

```bash
# 启动服务
sudo systemctl start grvt-balance-poll

# 查看服务状态
sudo systemctl status grvt-balance-poll
```

**预期输出**（服务正常运行）：
```
● grvt-balance-poll.service - GRVT Balance Polling Service
   Loaded: loaded (/etc/systemd/system/grvt-balance-poll.service; enabled; vendor preset: enabled)
   Active: active (running) since ...
```

## 步骤 12: 验证服务运行

```bash
# 查看实时日志（systemd journal）
sudo journalctl -u grvt-balance-poll -f

# 查看文件日志
tail -f /opt/grvt-balance-poll/logs/grvt_balance_poll.log

# 查看最近50行日志
sudo journalctl -u grvt-balance-poll -n 50
```

**检查日志中是否出现**：
- `Initialized client for ...` - 客户端初始化成功
- `GRVT balance polling started` - 轮询已启动
- `Total Equity: ...` - 余额查询成功

## 步骤 13: 配置开机自启（已自动配置）

安装脚本已自动启用开机自启，验证：

```bash
# 检查服务是否已启用
sudo systemctl is-enabled grvt-balance-poll

# 应该输出: enabled
```

如果需要手动启用/禁用：

```bash
# 启用开机自启
sudo systemctl enable grvt-balance-poll

# 禁用开机自启
sudo systemctl disable grvt-balance-poll
```

## 服务管理命令

### 基本操作

```bash
# 启动服务
sudo systemctl start grvt-balance-poll

# 停止服务
sudo systemctl stop grvt-balance-poll

# 重启服务
sudo systemctl restart grvt-balance-poll

# 查看服务状态
sudo systemctl status grvt-balance-poll

# 重新加载配置（修改 .env 后）
sudo systemctl restart grvt-balance-poll
```

### 日志查看

```bash
# 实时查看日志（按 Ctrl+C 退出）
sudo journalctl -u grvt-balance-poll -f

# 查看文件日志
tail -f /opt/grvt-balance-poll/logs/grvt_balance_poll.log

# 查看最近100行日志
sudo journalctl -u grvt-balance-poll -n 100

# 查看今天的日志
sudo journalctl -u grvt-balance-poll --since today

# 查看指定时间范围的日志
sudo journalctl -u grvt-balance-poll --since "2026-01-23 00:00:00" --until "2026-01-23 23:59:59"
```

## 故障排查

### 问题 1: 服务无法启动

**检查服务状态**：
```bash
sudo systemctl status grvt-balance-poll
```

**查看详细错误**：
```bash
sudo journalctl -u grvt-balance-poll -n 50 --no-pager
```

**常见原因**：
- `.env` 文件配置错误
- Python 依赖未安装
- 文件权限问题
- Python 路径不正确

### 问题 2: Python 模块未找到

**解决方法**：
```bash
# 检查 Python 模块是否安装
python3 -c "import grvt_pysdk"
python3 -c "import dotenv"

# 如果未安装，重新安装
sudo pip3 install grvt-pysdk python-dotenv

# 或者使用用户级安装
pip3 install --user grvt-pysdk python-dotenv

# 如果使用用户级安装，确保服务文件中的 Python 路径正确
```

### 问题 3: 权限错误

**解决方法**：
```bash
# 检查文件权限
ls -la /opt/grvt-balance-poll/

# 确保服务用户有权限
sudo chown -R grvt:grvt /opt/grvt-balance-poll
sudo chmod 755 /opt/grvt-balance-poll
sudo chmod 644 /opt/grvt-balance-poll/grvt_balance_poll.py
sudo chmod 600 /opt/grvt-balance-poll/.env
sudo chmod 755 /opt/grvt-balance-poll/logs
```

### 问题 4: 日志文件无法创建

**解决方法**：
```bash
# 确保日志目录存在且有写权限
sudo mkdir -p /opt/grvt-balance-poll/logs
sudo chown -R grvt:grvt /opt/grvt-balance-poll/logs
sudo chmod 755 /opt/grvt-balance-poll/logs
```

### 问题 5: 服务频繁重启

**查看重启原因**：
```bash
# 查看服务状态和重启历史
sudo systemctl status grvt-balance-poll
sudo journalctl -u grvt-balance-poll --since "1 hour ago" | grep -i error
```

**可能原因**：
- API 密钥配置错误
- 网络连接问题
- 代码错误导致崩溃

## 更新服务

当需要更新代码时：

```bash
# 1. 停止服务
sudo systemctl stop grvt-balance-poll

# 2. 备份当前版本（可选）
sudo cp /opt/grvt-balance-poll/grvt_balance_poll.py /opt/grvt-balance-poll/grvt_balance_poll.py.backup

# 3. 上传新版本文件
# （使用 scp、rsync 或 Git）

# 4. 设置权限
sudo chown grvt:grvt /opt/grvt-balance-poll/grvt_balance_poll.py
sudo chmod 644 /opt/grvt-balance-poll/grvt_balance_poll.py

# 5. 重启服务
sudo systemctl start grvt-balance-poll

# 6. 验证服务运行
sudo systemctl status grvt-balance-poll
```

## 卸载服务

如果需要完全卸载服务：

```bash
cd /opt/grvt-balance-poll

# 运行卸载脚本
sudo ./uninstall_service.sh

# 脚本会询问是否删除：
# - 安装目录
# - 服务用户
```

## 完整部署检查清单

部署完成后，使用以下清单验证：

- [ ] Python 3 已安装并可用
- [ ] pip3 已安装并可用
- [ ] 项目文件已上传到 `/opt/grvt-balance-poll`
- [ ] `.env` 文件已正确配置
- [ ] `.env` 文件权限为 600
- [ ] Python 依赖已安装（grvt-pysdk, python-dotenv）
- [ ] 服务已安装（`systemctl list-units | grep grvt-balance-poll`）
- [ ] 服务已启动（`systemctl is-active grvt-balance-poll`）
- [ ] 服务已启用开机自启（`systemctl is-enabled grvt-balance-poll`）
- [ ] 日志文件正常生成（`ls -la /opt/grvt-balance-poll/logs/`）
- [ ] 日志中显示余额查询成功
- [ ] 服务运行稳定（观察一段时间无异常重启）

## 快速部署脚本（可选）

如果需要快速部署，可以创建一个自动化脚本：

```bash
#!/bin/bash
# quick_deploy.sh - 快速部署脚本

set -e

echo "开始快速部署 GRVT Balance Poll 服务..."

# 更新系统
sudo apt update && sudo apt upgrade -y

# 安装 Python 和依赖
sudo apt install -y python3 python3-pip python3-venv build-essential python3-dev

# 安装 Python 包
sudo pip3 install grvt-pysdk python-dotenv

# 运行服务安装脚本
cd /opt/grvt-balance-poll
sudo ./install_service.sh

echo "部署完成！请确保 .env 文件已正确配置，然后启动服务："
echo "  sudo systemctl start grvt-balance-poll"
```

## 相关文档

- 详细配置说明：参见 [README.md](README.md)
- 环境变量说明：参见 [README.md#配置说明](README.md#配置说明)
- 故障排除：参见 [README.md#故障排除](README.md#故障排除)
