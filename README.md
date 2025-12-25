# GRVT 账户余额查询工具

这是一个用于定期查询 GRVT 账户余额的 Python 脚本，使用官方 GRVT Python SDK。

## 功能特性

- 支持同时监控多个账户余额
- 每分钟自动查询一次账户余额
- 显示总权益和所有资产的余额信息
- 使用 `.env` 文件管理配置，安全可靠
- 支持生产环境和测试环境

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

#### 多账户配置（推荐）

```
# 账户 1 配置
GRVT_API_KEY_1=your_first_api_key_here
GRVT_TRADING_ACCOUNT_ID_1=your_first_trading_account_id_here
GRVT_ENV_1=prod

# 账户 2 配置
GRVT_API_KEY_2=your_second_api_key_here
GRVT_TRADING_ACCOUNT_ID_2=your_second_trading_account_id_here
GRVT_ENV_2=prod

# 全局环境变量（如果单个账户未指定，则使用此值）
GRVT_ENV=prod
```

**说明：**
- 使用索引格式（`_1`, `_2`, `_3`...）可以配置多个账户
- 每个账户可以单独设置环境类型（`GRVT_ENV_1`, `GRVT_ENV_2` 等）
- 如果账户未指定环境类型，则使用全局 `GRVT_ENV` 的值
- `GRVT_PRIVATE_KEY_1`, `GRVT_PRIVATE_KEY_2` 等：可选，仅查询余额时不需要

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

编辑 `grvt_balance_poll.py` 文件，修改 `POLL_INTERVAL_SECONDS` 变量：

```python
POLL_INTERVAL_SECONDS = 60  # 修改为你想要的秒数
```

### 环境变量说明

#### 单账户配置（向后兼容）

| 变量名 | 必需 | 说明 |
|--------|------|------|
| `GRVT_API_KEY` | 是 | GRVT API 密钥 |
| `GRVT_TRADING_ACCOUNT_ID` | 是 | 交易账户 ID |
| `GRVT_ENV` | 否 | 环境类型，默认 `testnet` |
| `GRVT_PRIVATE_KEY` | 否 | 私钥，仅查询余额时不需要 |

#### 多账户配置

| 变量名 | 必需 | 说明 |
|--------|------|------|
| `GRVT_API_KEY_1`, `GRVT_API_KEY_2`, ... | 是 | 各账户的 API 密钥 |
| `GRVT_TRADING_ACCOUNT_ID_1`, `GRVT_TRADING_ACCOUNT_ID_2`, ... | 是 | 各账户的交易账户 ID |
| `GRVT_ENV_1`, `GRVT_ENV_2`, ... | 否 | 各账户的环境类型，未指定则使用全局 `GRVT_ENV` |
| `GRVT_ENV` | 否 | 全局环境类型，默认 `testnet` |
| `GRVT_PRIVATE_KEY_1`, `GRVT_PRIVATE_KEY_2`, ... | 否 | 各账户的私钥，仅查询余额时不需要 |

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

## 相关链接

- [GRVT API 文档](https://api-docs.grvt.io/api_setup/#python-sdk)
- [GRVT Python SDK](https://github.com/gravity-technologies/grvt-pysdk)

