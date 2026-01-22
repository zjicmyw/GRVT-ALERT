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

### 1. 安装依赖

```powershell
pip install grvt-pysdk python-dotenv
```

### 2. 配置环境变量

在项目根目录创建 `.env` 文件。

#### 单账户配置（向后兼容）

```
GRVT_API_KEY=your_api_key_here
GRVT_TRADING_ACCOUNT_ID=your_trading_account_id_here
GRVT_ENV=prod
```

#### 新格式配置（推荐）- 交易账户和资金账户独立配置

```
# 轮询配置
GRVT_POLL_INTERVAL=30  # 轮询间隔（秒），默认30秒

# 自动余额平衡配置
GRVT_BALANCE_THRESHOLD_PERCENT=43  # 触发自动转账的余额下限百分比
GRVT_BALANCE_TARGET_PERCENT=48  # 转账后的目标百分比

# Funding Sweep 配置
GRVT_FUNDING_SWEEP_THRESHOLD=100  # Funding账户资金归集阈值（默认100 USDT），超过此值自动归集到交易账户

# 交易账户 1 配置
GRVT_TRADING_API_KEY_1=your_trading_api_key_1
GRVT_TRADING_PRIVATE_KEY_1=your_trading_private_key_1
GRVT_TRADING_ACCOUNT_ID_1=your_trading_account_id_1
GRVT_RELATED_FUNDING_ACCOUNT_ID_1=your_funding_account_id_1  # 关联的资金账户ID（可选）
GRVT_RELATED_MAIN_ACCOUNT_ID_1=your_main_account_id_1  # 关联的主账户ID（可选）
GRVT_THRESHOLD_1=50000  # 告警阈值（可选）

# 资金账户 1 配置
GRVT_FUNDING_API_KEY_1=your_funding_api_key_1
GRVT_FUNDING_PRIVATE_KEY_1=your_funding_private_key_1
GRVT_FUNDING_ACCOUNT_ID_1=your_funding_account_id_1  # 内部账户ID（用于API调用）
GRVT_FUNDING_ACCOUNT_ADDRESS_1=0x...  # 资金账户的链上地址（以太坊地址，用于外部转账，必须在Address Book中登记）
GRVT_RELATED_TRADING_ACCOUNT_ID_1=your_trading_account_id_1  # 关联的交易账户ID（可选）
GRVT_RELATED_MAIN_ACCOUNT_ID_1=your_main_account_id_1  # 关联的主账户ID（可选）

# 交易账户 2 配置
GRVT_TRADING_API_KEY_2=your_trading_api_key_2
GRVT_TRADING_PRIVATE_KEY_2=your_trading_private_key_2
GRVT_TRADING_ACCOUNT_ID_2=your_trading_account_id_2
GRVT_RELATED_FUNDING_ACCOUNT_ID_2=your_funding_account_id_2
GRVT_RELATED_MAIN_ACCOUNT_ID_2=your_main_account_id_2
GRVT_THRESHOLD_2=30000  # 告警阈值（可选）

# 资金账户 2 配置
GRVT_FUNDING_API_KEY_2=your_funding_api_key_2
GRVT_FUNDING_PRIVATE_KEY_2=your_funding_private_key_2
GRVT_FUNDING_ACCOUNT_ID_2=your_funding_account_id_2  # 内部账户ID（用于API调用）
GRVT_FUNDING_ACCOUNT_ADDRESS_2=0x...  # 资金账户的链上地址（以太坊地址，用于外部转账，必须在Address Book中登记）
GRVT_RELATED_TRADING_ACCOUNT_ID_2=your_trading_account_id_2
GRVT_RELATED_MAIN_ACCOUNT_ID_2=your_main_account_id_2

# 全局环境变量（如果单个账户未指定，则使用此值）
GRVT_ENV=prod
```

**说明：**
- **交易账户和资金账户需要独立配置**：每个账户类型使用独立的 API key、私钥和账户ID
- **交易账户的API key**：支持内部转账（交易账户之间转账）
- **资金账户的API key**：支持内部转账（资金账户与交易账户之间）和外部转账（转到其他GRVT账户的资金账户）
- **关联账户ID**：用于转账操作时确定关联账户，如果交易账户和资金账户属于同一个主账户，可以配置关联ID
- **自动余额平衡**：只对交易账户进行自动平衡，当某个交易账户低于总资金的43%时，从另一个交易账户转账使其达到48%
- **向后兼容**：仍支持旧格式配置（`GRVT_API_KEY_X`, `GRVT_TRADING_ACCOUNT_ID_X` 等），会自动转换为交易账户配置

## 使用方法

### PowerShell 运行

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

## 输出示例

### 单账户输出

```
2025-12-25 14:50:19,082 INFO Initialized client for Account_1 (Trading Account ID: 5762245401578788)
2025-12-25 14:50:19,083 INFO GRVT balance polling started for 1 account(s) (interval 60s)
2025-12-25 14:50:20,123 INFO [Account_1] Total Equity: 50015.316456
2025-12-25 14:50:20,123 INFO [Account_1]   USDT: Balance=38734.740615, Index Price=0.999516898
```

### 多账户输出

```
2025-12-25 14:50:19,082 INFO Initialized client for Account_1 (Trading Account ID: 5762245401578788)
2025-12-25 14:50:19,083 INFO Initialized client for Account_2 (Trading Account ID: 1234567890123456)
2025-12-25 14:50:19,084 INFO GRVT balance polling started for 2 account(s) (interval 60s)
2025-12-25 14:50:20,123 INFO [Account_1] Total Equity: 50015.316456
2025-12-25 14:50:20,123 INFO [Account_1]   USDT: Balance=38734.740615, Index Price=0.999516898
2025-12-25 14:50:20,456 INFO [Account_2] Total Equity: 12345.678901
2025-12-25 14:50:20,456 INFO [Account_2]   USDT: Balance=10000.000000, Index Price=0.999517000
```

## 配置说明

### 修改查询间隔

在 `.env` 文件中配置 `GRVT_POLL_INTERVAL`：

```env
GRVT_POLL_INTERVAL=30  # 轮询间隔（秒），默认30秒
```

### 自动余额平衡配置

在 `.env` 文件中配置余额平衡参数：

```env
GRVT_BALANCE_THRESHOLD_PERCENT=43  # 触发自动转账的余额下限百分比
GRVT_BALANCE_TARGET_PERCENT=48  # 转账后的目标百分比
```

**工作原理**：
- 系统监控两个交易账户的总资金
- 当某个账户余额低于总资金的43%时，触发自动转账
- 从余额较多的账户转账到余额较少的账户，使其达到总资金的48%
- 转账操作有5分钟冷却期，防止频繁转账
- **安全约束**：转账金额会考虑可用余额和维持保证金，确保转账后不会导致保证金使用率过高
- **转账路径**：优先使用通过 funding 账户中转的路径（A-trading → A-funding → B-funding → B-trading），更安全且支持外部转账

**Funding Sweep 功能**：
- 自动将 funding 账户中超过阈值的资金归集到 trading 账户
- 避免资金"卡"在 funding 账户导致 trading 可用余额不足
- 默认阈值为 100 USDT，可通过 `GRVT_FUNDING_SWEEP_THRESHOLD` 配置

### 环境变量说明

#### 新格式配置（推荐）- 交易账户和资金账户独立配置

| 变量名 | 必需 | 说明 |
|--------|------|------|
| `GRVT_POLL_INTERVAL` | 否 | 轮询间隔（秒），默认30秒 |
| `GRVT_BALANCE_THRESHOLD_PERCENT` | 否 | 自动转账触发阈值（百分比），默认43% |
| `GRVT_BALANCE_TARGET_PERCENT` | 否 | 转账后目标百分比，默认48% |
| `GRVT_FUNDING_SWEEP_THRESHOLD` | 否 | Funding账户资金归集阈值（USDT），默认100 |
| `GRVT_TRADING_API_KEY_X` | 是* | 交易账户X的API密钥（需要转账权限，用于交易账户间转账） |
| `GRVT_TRADING_PRIVATE_KEY_X` | 是* | 交易账户X的私钥（需要转账权限） |
| `GRVT_TRADING_ACCOUNT_ID_X` | 是* | 交易账户X的账户ID |
| `GRVT_FUNDING_API_KEY_X` | 否 | 资金账户X的API密钥（需要转账权限，用于内部和外部转账） |
| `GRVT_FUNDING_PRIVATE_KEY_X` | 否 | 资金账户X的私钥（需要转账权限） |
| `GRVT_FUNDING_ACCOUNT_ID_X` | 否 | 资金账户X的内部账户ID（用于API调用） |
| `GRVT_FUNDING_ACCOUNT_ADDRESS_X` | 否 | 资金账户X的链上地址（以太坊地址，用于外部转账，必须在Address Book中登记） |
| `GRVT_RELATED_TRADING_ACCOUNT_ID_X` | 否 | 资金账户X关联的交易账户ID（用于转账） |
| `GRVT_RELATED_FUNDING_ACCOUNT_ID_X` | 否 | 交易账户X关联的资金账户ID（用于转账） |
| `GRVT_RELATED_MAIN_ACCOUNT_ID_X` | 否 | 账户X关联的主账户ID（用于转账） |
| `GRVT_THRESHOLD_X` | 否 | 账户X的告警阈值 |
| `GRVT_ENV_X` | 否 | 账户X的环境类型，未指定则使用全局 `GRVT_ENV` |
| `GRVT_ENV` | 否 | 全局环境类型，默认 `prod` |

*注：至少需要配置一个交易账户才能进行余额查询和自动平衡。

#### 旧格式配置（向后兼容）

| 变量名 | 必需 | 说明 |
|--------|------|------|
| `GRVT_API_KEY` | 是 | GRVT API 密钥（会自动转换为交易账户配置） |
| `GRVT_TRADING_ACCOUNT_ID` | 是 | 交易账户 ID |
| `GRVT_ENV` | 否 | 环境类型，默认 `prod` |
| `GRVT_PRIVATE_KEY` | 否 | 私钥，仅查询余额时不需要 |

## 注意事项

1. **安全提示**
   - `.env` 文件已添加到 `.gitignore`，不会被提交到版本控制
   - 请妥善保管你的 API 密钥和账户信息
   - 不要将 `.env` 文件分享给他人

2. **API 限制**
   - 请遵守 GRVT API 的速率限制
   - 默认查询间隔为 60 秒，可根据需要调整

3. **错误处理**
   - 脚本会自动处理网络错误和 API 错误
   - 错误信息会记录在日志中

## 故障排除

### 问题：`Non-hexadecimal digit found` 错误

**原因：** `.env` 文件可能包含 BOM（字节顺序标记）或格式不正确。

**解决方法：** 重新创建 `.env` 文件，确保使用 UTF-8 编码且无 BOM。

### 问题：`Missing required environment variables` 或 `No account configuration found` 错误

**原因：** `.env` 文件中缺少必需的环境变量。

**解决方法：** 
- 单账户：检查 `.env` 文件，确保包含 `GRVT_API_KEY` 和 `GRVT_TRADING_ACCOUNT_ID`
- 多账户：检查 `.env` 文件，确保包含 `GRVT_API_KEY_1` 和 `GRVT_TRADING_ACCOUNT_ID_1`（至少配置一个账户）

### 问题：`Failed to initialize GRVT client` 错误

**原因：** API 密钥或账户 ID 不正确，或网络连接问题。

**解决方法：** 
1. 检查 `.env` 文件中的配置是否正确
2. 确认网络连接正常
3. 验证 API 密钥是否有查询余额的权限

### 问题：`Transfer private key not configured` 或 `Private key not configured` 错误

**原因：** 转账功能需要转账权限的私钥，但未配置。

**解决方法：** 
1. 对于交易账户间转账：在 `.env` 文件中配置 `GRVT_TRADING_PRIVATE_KEY_X`（需要转账权限）
2. 对于涉及资金账户的转账：在 `.env` 文件中配置 `GRVT_FUNDING_PRIVATE_KEY_X`（需要转账权限）
3. 确保私钥对应的 API key 具有转账权限（不能使用只读 API key）

### 问题：`Config must be a trading account config` 或 `Config must be a funding account config` 错误

**原因：** 转账函数使用了错误的账户类型配置。

**解决方法：**
- 交易账户间转账：使用交易账户的配置
- 涉及资金账户的转账：使用资金账户的配置（因为资金账户支持内部转账）

### 问题：认证失败，出现 `'NoneType' object has no attribute 'items'` 错误

**原因：** 这是 GRVT SDK (grvt-pysdk 0.2.1) 的一个已知问题。SDK在cookie认证处理时可能出现错误。

**解决方法：**
1. **检查API密钥配置**：确保所有账户的 `GRVT_TRADING_API_KEY_X` 和 `GRVT_FUNDING_API_KEY_X` 都已正确配置
2. **检查私钥配置**：虽然只读查询不需要私钥，但SDK可能期望私钥存在。确保配置了 `GRVT_TRADING_PRIVATE_KEY_X` 和 `GRVT_FUNDING_PRIVATE_KEY_X`（即使只读，也可以使用只读API key对应的私钥，或使用空字符串）
3. **更新SDK版本**：尝试更新到最新版本的 grvt-pysdk：
   ```bash
   pip install --upgrade grvt-pysdk
   ```
4. **检查网络连接**：确保能够正常访问 GRVT API 服务器
5. **临时解决方案**：如果问题持续，可以尝试：
   - 重新生成API密钥
   - 检查API密钥权限（确保有查询余额的权限）
   - 联系GRVT技术支持

### 问题：外部转账失败或提示地址未在Address Book中

**原因：** 资金账户之间的外部转账需要使用地址，且目标地址必须在GRVT的Address Book中预先登记。

**解决方法：**
1. 在GRVT网页端的"Address Book"中添加目标资金账户地址
2. 确保配置了 `GRVT_FUNDING_ACCOUNT_ADDRESS_X`（资金账户的链上地址）
3. 地址格式应为以太坊地址（0x开头）
4. 验证地址是否正确（可在GRVT账户设置中查看Funding Wallet Address）

### 问题：自动转账不工作

**原因：** 可能的原因包括：账户数量不足、余额不足、冷却期内、转账权限配置错误。

**解决方法：** 
1. 确保配置了两个账户
2. 检查账户余额是否足够
3. 检查是否在5分钟冷却期内
4. 验证转账API密钥和私钥是否正确配置
5. 查看日志中的详细错误信息

## 相关链接

- [GRVT API 文档](https://api-docs.grvt.io/api_setup/#python-sdk)
- [GRVT Python SDK](https://github.com/gravity-technologies/grvt-pysdk)

