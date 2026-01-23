# GRVT 账户余额查询工具

这是一个用于定期查询 GRVT 账户余额的 Python 脚本，使用官方 GRVT Python SDK。

## 功能特性

- 支持同时监控多个账户余额（交易账户和资金账户独立配置）
- 可配置轮询间隔（默认30秒）持续查询余额
- 自动余额平衡：监控两个交易账户，当余额不平衡时自动转账
- 支持交易账户与资金账户之间的双向划转
- 支持资金账户之间的外部转账（转到其他GRVT账户）
- 阈值告警：余额低于设定值时立即发送通知
- 每日汇总：所有账户正常时，每天指定时间发送汇总消息
- 使用 `.env` 文件管理配置，安全可靠
- 支持生产环境和测试环境
- 清晰的日志输出：SDK内部日志已静默，只显示关键操作信息

## 账户类型说明

GRVT 系统中有两种账户类型：

1. **交易账户（Trading Account）**
   - 用于交易操作
   - 支持内部转账（交易账户之间转账）
   - 需要独立的 API key 和私钥（具有转账权限）

2. **资金账户（Funding Account）**
   - 用于充值和提币操作
   - 支持内部转账（资金账户与交易账户之间）
   - 支持外部转账（转到其他GRVT账户的资金账户，使用**链上地址**而非账户ID）
   - 需要独立的 API key 和私钥（具有转账权限）
   - **重要**：资金账户使用**以太坊地址**（Funding Wallet Address）作为链上标识
   - **重要**：外部转账前，目标地址必须在GRVT的Address Book中预先登记

## 安装步骤

### 本地开发环境（Windows/PowerShell）

#### 1. 安装依赖

```powershell
pip install grvt-pysdk python-dotenv
```

#### 2. 配置环境变量

复制 `.env.example` 到 `.env` 并填写你的配置：

```powershell
cp .env.example .env
```

详细配置说明见下方 [配置说明](#配置说明) 部分。

### Ubuntu 生产环境部署

**重要**：如果是首次在 Ubuntu 服务器上部署，请参考详细的部署文档：

👉 **[完整部署指南](DEPLOYMENT.md)** - 包含从零开始的完整安装步骤

**快速开始**（如果系统已配置好 Python 环境）：

1. 上传项目文件到服务器
2. 配置 `.env` 文件
3. 安装依赖：`sudo pip3 install grvt-pysdk python-dotenv`
4. 运行安装脚本：`sudo ./install_service.sh`
5. 启动服务：`sudo systemctl start grvt-balance-poll`

## 快速开始

### 运行脚本

```powershell
# 切换到项目目录
cd D:\Code\GRVT

# 清除可能存在的环境变量（避免冲突）
Remove-Item Env:GRVT_* -ErrorAction SilentlyContinue

# 运行脚本
python grvt_balance_poll.py
```

### 停止脚本

按 `Ctrl + C` 停止脚本。

## 作为系统服务运行（Ubuntu/Linux）

在生产环境中，建议将脚本配置为 systemd 服务，以实现：
- 开机自动启动
- 进程崩溃自动重启
- 后台运行，不依赖终端
- 日志持久化到文件

### 前置要求

- Ubuntu 18.04 或更高版本
- sudo 权限
- 网络连接

### 快速部署（推荐）

**一键部署脚本**（自动完成所有步骤）：

```bash
# 1. 上传项目文件到服务器后，进入项目目录
cd /opt/grvt-balance-poll

# 2. 给脚本执行权限
chmod +x deploy.sh

# 3. 运行一键部署脚本
sudo ./deploy.sh
```

**脚本会自动完成**：
- ✅ 检查系统环境
- ✅ 更新系统包（可选）
- ✅ 安装 Python 3 和 pip（如果未安装）
- ✅ 安装系统依赖（build-essential, python3-dev 等）
- ✅ 安装 Python 包（grvt-pysdk, python-dotenv）
- ✅ 准备项目目录和文件
- ✅ 创建服务用户
- ✅ 配置 systemd 服务
- ✅ 启动服务（可选）

**如果是全新 Ubuntu 服务器，强烈推荐使用一键部署脚本。** 

**重要提示**：如果从 Windows 上传文件，可能需要修复行尾符：
```bash
sudo apt install -y dos2unix
dos2unix deploy.sh install_service.sh uninstall_service.sh
chmod +x deploy.sh
sudo ./deploy.sh
```

**详细步骤**：如需手动控制每个步骤，请参考 [完整部署指南](DEPLOYMENT.md)。

**故障排查**：如遇到问题，请参考 [故障排查指南](TROUBLESHOOTING.md)。

### 安装服务

1. **确保 Python 环境已配置**：
   ```bash
   python3 --version  # 应显示 Python 3.8+
   pip3 --version      # 应显示 pip 版本
   ```

2. **安装 Python 依赖**（如果未安装）：
   ```bash
   sudo pip3 install grvt-pysdk python-dotenv
   ```

3. **运行安装脚本**：
   ```bash
   sudo ./install_service.sh
   ```

4. **配置环境变量**：
   确保 `/opt/grvt-balance-poll/.env` 文件已正确配置（安装脚本会复制 `.env` 文件）
   ```bash
   sudo nano /opt/grvt-balance-poll/.env
   ```

5. **启动服务**：
   ```bash
   sudo systemctl start grvt-balance-poll
   ```

6. **查看服务状态**：
   ```bash
   sudo systemctl status grvt-balance-poll
   ```

### 服务管理命令

```bash
# 启动服务
sudo systemctl start grvt-balance-poll

# 停止服务
sudo systemctl stop grvt-balance-poll

# 重启服务
sudo systemctl restart grvt-balance-poll

# 查看服务状态
sudo systemctl status grvt-balance-poll

# 查看实时日志（systemd journal）
sudo journalctl -u grvt-balance-poll -f

# 查看文件日志
tail -f /opt/grvt-balance-poll/logs/grvt_balance_poll.log

# 查看最近100行日志
sudo journalctl -u grvt-balance-poll -n 100

# 启用开机自启（安装时已自动启用）
sudo systemctl enable grvt-balance-poll

# 禁用开机自启
sudo systemctl disable grvt-balance-poll
```

### 更新服务

**重要**：更新代码文件后，必须清除 Python 缓存才能确保新代码生效。

**一行命令快速更新**：

```bash
# 同时更新 Python 文件和 .env 文件（推荐）
chmod +x update_service.sh && dos2unix update_service.sh 2>/dev/null || true && sudo ./update_service.sh ./grvt_balance_poll.py ./.env

# 仅更新 Python 文件
chmod +x update_service.sh && dos2unix update_service.sh 2>/dev/null || true && sudo ./update_service.sh ./grvt_balance_poll.py

# 仅更新 .env 文件
chmod +x update_service.sh && dos2unix update_service.sh 2>/dev/null || true && sudo ./update_service.sh '' ./.env
```

**详细使用方法**：

```bash
# 确保脚本有执行权限并修复行尾符
chmod +x update_service.sh
dos2unix update_service.sh 2>/dev/null || true

# 更新 Python 文件
sudo ./update_service.sh ./grvt_balance_poll.py

# 同时更新 Python 文件和 .env 文件
sudo ./update_service.sh ./grvt_balance_poll.py ./.env

# 仅更新 .env 文件
sudo ./update_service.sh '' ./.env

# 或者仅清除缓存和重启（不更新文件）
sudo ./update_service.sh
```

**方法 2：手动更新**

```bash
# 1. 停止服务并等待
sudo systemctl stop grvt-balance-poll
sleep 2

# 2. 清除 Python 缓存（重要！）
sudo find /opt/grvt-balance-poll -type d -name __pycache__ -exec rm -r {} + 2>/dev/null || true
sudo find /opt/grvt-balance-poll -name "*.pyc" -delete 2>/dev/null || true

# 3. 备份当前文件（可选）
sudo cp /opt/grvt-balance-poll/grvt_balance_poll.py /opt/grvt-balance-poll/grvt_balance_poll.py.backup
sudo cp /opt/grvt-balance-poll/.env /opt/grvt-balance-poll/.env.backup

# 4. 替换文件（使用 scp、rsync 等方式上传新文件）
# scp grvt_balance_poll.py user@server:/opt/grvt-balance-poll/
# scp .env user@server:/opt/grvt-balance-poll/

# 5. 设置权限
sudo chown grvt:grvt /opt/grvt-balance-poll/grvt_balance_poll.py
sudo chmod 644 /opt/grvt-balance-poll/grvt_balance_poll.py
sudo chown grvt:grvt /opt/grvt-balance-poll/.env
sudo chmod 600 /opt/grvt-balance-poll/.env

# 6. 重启服务
sudo systemctl restart grvt-balance-poll

# 7. 验证
sudo systemctl status grvt-balance-poll
```

**为什么需要清除缓存？**

Python 会将 `.py` 文件编译为 `.pyc` 字节码文件并缓存在 `__pycache__` 目录中。如果只替换 `.py` 文件而不清除缓存，Python 可能会继续使用旧的字节码文件，导致代码更新不生效。

### 卸载服务

```bash
sudo ./uninstall_service.sh
```

### 日志文件

- **Systemd Journal**: 使用 `journalctl -u grvt-balance-poll` 查看
- **文件日志**: `/opt/grvt-balance-poll/logs/grvt_balance_poll.log`
  - 日志文件每天轮转
  - 保留最近30天的日志
  - 自动压缩旧日志

### 服务配置说明

- **服务用户**: `grvt`（自动创建，无登录权限）
- **安装目录**: `/opt/grvt-balance-poll`
- **工作目录**: `/opt/grvt-balance-poll`
- **自动重启**: 服务崩溃后10秒自动重启
- **日志目录**: `/opt/grvt-balance-poll/logs/`

## 输出示例

### 正常余额查询输出

```
2026-01-23 01:15:56,239 INFO [root] Initialized client for Trading_8788 (Trading Account ID: 5762245401578788)
2026-01-23 01:15:56,239 INFO [root] GRVT balance polling started for 4 account(s) (interval 30s)
2026-01-23 01:15:56,239 INFO [root] Balance threshold: 48.7%, target: 49.0%
2026-01-23 01:15:56,301 INFO [root] [Trading_8788] Total Equity: 66324.343461
2026-01-23 01:15:57,350 INFO [root] [Funding_145b] Funding Account Total Equity: 0.009938
2026-01-23 01:15:57,419 INFO [root] [Trading_2974] Total Equity: 70081.573511
2026-01-23 01:15:58,907 INFO [root] [Funding_cb27] Funding Account Total Equity: 0.0
```

### 自动再平衡输出

```
2026-01-23 01:15:58,907 INFO [root] [Auto-Balance] Rebalancing: Transferring 514.56 USDT from Trading_2974 to Trading_8788 (Trading_2974: 51.38%, Trading_8788: 48.62%)
2026-01-23 01:16:08,517 INFO [root] [Transfer] Step 1/3: Trading_2974 → Funding_cb27 (tx_id: 81277815)
2026-01-23 01:16:13,592 INFO [root] [Transfer] Step 2/3: Funding_cb27 → Funding_145b (tx_id: 81277832)
2026-01-23 01:16:14,600 INFO [root] [Transfer] Step 3/3: Funding_145b → Trading_8788 (tx_id: 81277838)
2026-01-23 01:16:14,872 INFO [root] [Transfer] ✓ Completed: 514.56 USDT from Trading_2974 to Trading_8788 (tx_ids: 81277815, 81277832, 81277838)
2026-01-23 01:16:14,878 INFO [root] [Auto-Balance] Transfer completed successfully
```

**注意**：SDK 内部的 cookie 刷新和 HTTP 请求日志已静默，输出更加清晰易读。

## 配置说明

### 基本配置

在 `.env` 文件中配置以下基本参数：

```env
# 轮询配置
GRVT_POLL_INTERVAL=30  # 轮询间隔（秒），默认30秒

# 自动余额平衡配置
GRVT_BALANCE_THRESHOLD_PERCENT=43  # 触发自动转账的余额下限百分比
GRVT_BALANCE_TARGET_PERCENT=48  # 转账后的目标百分比

# Funding Sweep 配置
GRVT_FUNDING_SWEEP_THRESHOLD=100  # Funding账户资金归集阈值（默认100 USDT）

# 日志级别配置
GRVT_LOG_LEVEL=INFO  # 日志级别：DEBUG（详细日志）或 INFO（默认，简洁日志）

# 通知配置
GRVT_DAILY_SUMMARY_TIME=16:30  # 每日汇总发送时间（北京时间，HH:MM）
GRVT_ALERT_DEVICE_KEY=your_bark_device_key_here  # Bark 通知设备密钥

# 全局环境变量
GRVT_ENV=prod  # 环境类型：prod（生产）、testnet（测试网）、staging、dev
```

### 账户配置

#### 交易账户配置

```env
# 交易账户 1 配置
GRVT_TRADING_API_KEY_1=your_trading_api_key_1
GRVT_TRADING_PRIVATE_KEY_1=your_trading_private_key_1
GRVT_TRADING_ACCOUNT_ID_1=your_trading_account_id_1
GRVT_RELATED_FUNDING_ACCOUNT_ID_1=your_funding_account_address_1  # 关联的资金账户地址（以太坊地址）
GRVT_RELATED_MAIN_ACCOUNT_ID_1=your_main_account_id_1  # 关联的主账户ID
GRVT_THRESHOLD_1=50000  # 告警阈值（可选）
GRVT_ENV_1=prod  # 账户环境类型（可选，未指定则使用全局 GRVT_ENV）
```

#### 资金账户配置

```env
# 资金账户 1 配置
GRVT_FUNDING_API_KEY_1=your_funding_api_key_1
GRVT_FUNDING_PRIVATE_KEY_1=your_funding_private_key_1
GRVT_FUNDING_ACCOUNT_ID_1=your_funding_account_id_1  # 内部账户ID（用于API调用）
GRVT_FUNDING_ACCOUNT_ADDRESS_1=0x...  # 资金账户的链上地址（以太坊地址，用于外部转账，必须在Address Book中登记）
GRVT_RELATED_TRADING_ACCOUNT_ID_1=your_trading_account_id_1  # 关联的交易账户ID
GRVT_RELATED_MAIN_ACCOUNT_ID_1=your_main_account_id_1  # 关联的主账户ID
GRVT_ENV_1=prod  # 账户环境类型（可选）
```

**重要说明**：
- **交易账户和资金账户需要独立配置**：每个账户类型使用独立的 API key、私钥和账户ID
- **交易账户的API key**：需要"Transfer"权限，支持内部转账（交易账户到自己的资金账户）
- **资金账户的API key**：需要"Internal Transfer"和"External Transfer"权限
- **GRVT_RELATED_FUNDING_ACCOUNT_ID_X**：应该是资金账户的**以太坊地址**（即 `GRVT_FUNDING_ACCOUNT_ADDRESS_X` 的值），不是内部账户ID
- **自动余额平衡**：只对交易账户进行自动平衡，当某个交易账户低于总资金的阈值百分比时，从另一个交易账户转账使其达到目标百分比

### 单账户配置（向后兼容）

仍支持旧格式配置：

```env
GRVT_API_KEY=your_api_key_here
GRVT_TRADING_ACCOUNT_ID=your_trading_account_id_here
GRVT_ENV=prod
```

### 环境变量完整列表

#### 全局配置

| 变量名 | 必需 | 默认值 | 说明 |
|--------|------|--------|------|
| `GRVT_POLL_INTERVAL` | 否 | 30 | 轮询间隔（秒） |
| `GRVT_BALANCE_THRESHOLD_PERCENT` | 否 | 43 | 自动转账触发阈值（百分比） |
| `GRVT_BALANCE_TARGET_PERCENT` | 否 | 48 | 转账后目标百分比 |
| `GRVT_FUNDING_SWEEP_THRESHOLD` | 否 | 100 | Funding账户资金归集阈值（USDT） |
| `GRVT_LOG_LEVEL` | 否 | INFO | 日志级别：DEBUG 或 INFO |
| `GRVT_DAILY_SUMMARY_TIME` | 否 | - | 每日汇总发送时间（北京时间，HH:MM） |
| `GRVT_ALERT_DEVICE_KEY` | 否 | - | Bark 通知设备密钥 |
| `GRVT_ENV` | 否 | prod | 全局环境类型 |

#### 交易账户配置（X = 1, 2, ...）

| 变量名 | 必需 | 说明 |
|--------|------|------|
| `GRVT_TRADING_API_KEY_X` | 是* | 交易账户X的API密钥（需要Transfer权限） |
| `GRVT_TRADING_PRIVATE_KEY_X` | 是* | 交易账户X的私钥（需要Transfer权限） |
| `GRVT_TRADING_ACCOUNT_ID_X` | 是* | 交易账户X的账户ID |
| `GRVT_RELATED_FUNDING_ACCOUNT_ID_X` | 否 | 关联的资金账户地址（以太坊地址，用于转账） |
| `GRVT_RELATED_MAIN_ACCOUNT_ID_X` | 否 | 关联的主账户ID（用于转账） |
| `GRVT_THRESHOLD_X` | 否 | 账户X的告警阈值 |
| `GRVT_ENV_X` | 否 | 账户X的环境类型 |

#### 资金账户配置（X = 1, 2, ...）

| 变量名 | 必需 | 说明 |
|--------|------|------|
| `GRVT_FUNDING_API_KEY_X` | 否 | 资金账户X的API密钥（需要Internal Transfer和External Transfer权限） |
| `GRVT_FUNDING_PRIVATE_KEY_X` | 否 | 资金账户X的私钥（需要转账权限） |
| `GRVT_FUNDING_ACCOUNT_ID_X` | 否 | 资金账户X的内部账户ID（用于API调用） |
| `GRVT_FUNDING_ACCOUNT_ADDRESS_X` | 否 | 资金账户X的链上地址（以太坊地址，用于外部转账，必须在Address Book中登记） |
| `GRVT_RELATED_TRADING_ACCOUNT_ID_X` | 否 | 资金账户X关联的交易账户ID |
| `GRVT_RELATED_MAIN_ACCOUNT_ID_X` | 否 | 资金账户X关联的主账户ID |
| `GRVT_ENV_X` | 否 | 账户X的环境类型 |

*注：至少需要配置一个交易账户才能进行余额查询和自动平衡。

## 功能详解

### 自动余额平衡

**工作原理**：
- 系统监控两个交易账户的总资金
- 当某个账户余额低于总资金的阈值百分比（默认43%）时，触发自动转账
- 从余额较多的账户转账到余额较少的账户，使其达到目标百分比（默认48%）
- 转账操作有5分钟冷却期，防止频繁转账

**安全约束**：
- 转账金额会考虑可用余额和维持保证金，确保转账后不会导致保证金使用率过高
- 转账路径：通过 funding 账户中转（A-trading → A-funding → B-funding → B-trading），更安全且支持外部转账

**配置示例**：
```env
GRVT_BALANCE_THRESHOLD_PERCENT=43  # 触发阈值
GRVT_BALANCE_TARGET_PERCENT=48     # 目标百分比
```

### Funding Sweep 功能

自动将 funding 账户中超过阈值的资金归集到 trading 账户，避免资金"卡"在 funding 账户导致 trading 可用余额不足。

**配置示例**：
```env
GRVT_FUNDING_SWEEP_THRESHOLD=100  # 阈值（USDT），默认100
```

### 日志级别

通过 `GRVT_LOG_LEVEL` 环境变量控制日志详细程度：

- **INFO**（默认）：显示关键操作信息，SDK内部日志已静默
- **DEBUG**：显示详细调试信息，包括完整的转账日志和SDK内部日志

**配置示例**：
```env
GRVT_LOG_LEVEL=INFO   # 简洁日志（推荐）
GRVT_LOG_LEVEL=DEBUG  # 详细日志（用于调试）
```

## 注意事项

1. **安全提示**
   - `.env` 文件已添加到 `.gitignore`，不会被提交到版本控制
   - 请妥善保管你的 API 密钥和账户信息
   - 不要将 `.env` 文件分享给他人

2. **API 限制**
   - 请遵守 GRVT API 的速率限制
   - 默认查询间隔为 30 秒，可根据需要调整

3. **错误处理**
   - 脚本会自动处理网络错误和 API 错误
   - 错误信息会记录在日志中

4. **转账权限要求**
   - 交易账户的API key需要"Transfer"权限（用于内部转账到自己的资金账户）
   - 资金账户的API key需要"Internal Transfer"和"External Transfer"权限
   - 只读API key无法进行转账操作

## 故障排除

### 问题：`Non-hexadecimal digit found` 错误

**原因**：`.env` 文件可能包含 BOM（字节顺序标记）或格式不正确。

**解决方法**：重新创建 `.env` 文件，确保使用 UTF-8 编码且无 BOM。

### 问题：`Missing required environment variables` 或 `No account configuration found` 错误

**原因**：`.env` 文件中缺少必需的环境变量。

**解决方法**：
- 单账户：检查 `.env` 文件，确保包含 `GRVT_API_KEY` 和 `GRVT_TRADING_ACCOUNT_ID`
- 多账户：检查 `.env` 文件，确保包含 `GRVT_TRADING_API_KEY_1` 和 `GRVT_TRADING_ACCOUNT_ID_1`（至少配置一个账户）

### 问题：`Failed to initialize GRVT client` 错误

**原因**：API 密钥或账户 ID 不正确，或网络连接问题。

**解决方法**：
1. 检查 `.env` 文件中的配置是否正确
2. 确认网络连接正常
3. 验证 API 密钥是否有查询余额的权限

### 问题：`Transfer private key not configured` 或 `Private key not configured` 错误

**原因**：转账功能需要转账权限的私钥，但未配置。

**解决方法**：
1. 对于交易账户间转账：在 `.env` 文件中配置 `GRVT_TRADING_PRIVATE_KEY_X`（需要Transfer权限）
2. 对于涉及资金账户的转账：在 `.env` 文件中配置 `GRVT_FUNDING_PRIVATE_KEY_X`（需要Internal Transfer和External Transfer权限）
3. 确保私钥对应的 API key 具有转账权限（不能使用只读 API key）

### 问题：`Config must be a trading account config` 或 `Config must be a funding account config` 错误

**原因**：转账函数使用了错误的账户类型配置。

**解决方法**：
- 交易账户到资金账户：使用交易账户的配置（交易账户API key有权限转给自己的资金账户）
- 资金账户到资金账户：使用资金账户的配置（资金账户API key有权限进行外部转账）
- 资金账户到交易账户：使用资金账户的配置（资金账户API key有权限转给自己的交易账户）

### 问题：认证失败，出现 `'NoneType' object has no attribute 'items'` 错误

**原因**：这是 GRVT SDK 的一个已知问题。SDK在cookie认证处理时可能出现错误。

**解决方法**：
1. **检查API密钥配置**：确保所有账户的 `GRVT_TRADING_API_KEY_X` 和 `GRVT_FUNDING_API_KEY_X` 都已正确配置
2. **检查私钥配置**：虽然只读查询不需要私钥，但SDK可能期望私钥存在。确保配置了 `GRVT_TRADING_PRIVATE_KEY_X` 和 `GRVT_FUNDING_PRIVATE_KEY_X`
3. **检查IP白名单**：确保当前IP地址已添加到API key的白名单中
4. **更新SDK版本**：尝试更新到最新版本的 grvt-pysdk：
   ```bash
   pip install --upgrade grvt-pysdk
   ```
5. **检查网络连接**：确保能够正常访问 GRVT API 服务器

### 问题：外部转账失败或提示地址未在Address Book中

**原因**：资金账户之间的外部转账需要使用地址，且目标地址必须在GRVT的Address Book中预先登记。

**解决方法**：
1. 在GRVT网页端的"Address Book"中添加目标资金账户地址
2. 确保配置了 `GRVT_FUNDING_ACCOUNT_ADDRESS_X`（资金账户的链上地址）
3. 地址格式应为以太坊地址（0x开头）
4. 验证地址是否正确（可在GRVT账户设置中查看Funding Wallet Address）

### 问题：自动转账不工作

**原因**：可能的原因包括：账户数量不足、余额不足、冷却期内、转账权限配置错误。

**解决方法**：
1. 确保配置了两个交易账户
2. 检查账户余额是否足够
3. 检查是否在5分钟冷却期内
4. 验证转账API密钥和私钥是否正确配置
5. 确保资金账户配置完整（`GRVT_FUNDING_ACCOUNT_ADDRESS_X` 等）
6. 查看日志中的详细错误信息（设置 `GRVT_LOG_LEVEL=DEBUG` 获取更多信息）

### 问题：IP 地址未在白名单中

**原因**：API key 配置了IP白名单限制，当前IP地址不在白名单中。

**解决方法**：
1. 在GRVT网页端（Settings > API Keys）为 API key 添加当前 IP 地址到白名单
2. 查看当前 IP：https://api.ipify.org
3. 或者移除 IP 白名单限制（如果允许）

## 相关链接

- [GRVT API 文档](https://api-docs.grvt.io/api_setup/#python-sdk)
- [GRVT Python SDK](https://github.com/gravity-technologies/grvt-pysdk)
