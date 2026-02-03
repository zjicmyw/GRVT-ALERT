# GRVT 余额轮询工具 - 需求与规格说明

> **读者**：AI 与开发者。用于二次开发、重构或功能规划。  
> **来源**：基于 README.md、grvt_balance_poll.py 与 .env.example 整理。  
> **语言**：中文。

---

## 1. 项目概览

| 项 | 说明 |
|----|------|
| **名称** | GRVT Balance Poll（GRVT 余额轮询工具） |
| **用途** | 定期查询 GRVT 账户余额并执行自动余额管理。 |
| **技术栈** | Python 3.8+、grvt-pysdk、python-dotenv |
| **入口** | `grvt_balance_poll.py` → `main()` |
| **配置** | `.env`（参考 `.env.example`）；无配置文件路径参数。 |

### 1.1 核心能力

- **多账户监控**：支持多个交易账户与资金账户，各自独立配置。
- **轮询**：可配置间隔（默认 30 秒）；单进程、单循环。
- **自动平衡**：仅在两个交易账户之间；当某账户占总资金比例低于阈值时触发再平衡。
- **转账**：交易账户 ↔ 资金账户（内部）、资金账户 → 资金账户（外部，按链上地址）。
- **Funding Sweep**：资金账户余额超过阈值时，将超出部分归集到关联交易账户。
- **告警**：按阈值告警（余额低于配置值）；每日汇总在指定时间（北京时间）发送；**可转余额不足告警**（从交易账户转到资金账户时可用余额不够则发 Bark，告警后继续执行转账尝试）。
- **通知**：可选 Bark，通过 `GRVT_ALERT_DEVICE_KEY` 配置。可转余额不足告警与阈值告警共用该配置；**相同内容（同一账户+同一方向）20 分钟内只发一次**。

### 1.2 账户类型（GRVT）

| 类型 | 说明 | 职责 |
|------|------|------|
| **Trading** | 交易账户 | 交易；可内部划转到自己的资金账户。 |
| **Funding** | 资金账户 | 充值/提币；可内部划转到自己的交易账户；可向其他 GRVT 资金账户外部划转（按以太坊地址）。 |

- 每种账户类型使用各自的 API Key 和私钥。
- **交易账户 → 交易账户** 的再平衡必须**经资金账户**：A_交易 → A_资金 → B_资金 → B_交易。

---

## 2. 需求摘要

### 2.1 功能需求

| 编号 | 需求 | 备注 |
|------|------|------|
| F1 | 从 `.env` 加载 N 个交易账户、M 个资金账户（余额轮询需 N≥1；自动平衡需 N=2）。 | 见 §4 配置。 |
| F2 | 每 `GRVT_POLL_INTERVAL` 秒：查询交易账户余额（可选查询资金账户）。 | 主循环。 |
| F3 | 当恰好有 2 个交易账户且余额占比低于阈值时：计算转账金额并经由资金账户路径执行。 | 自动平衡。 |
| F4 | 当资金账户余额 > `GRVT_FUNDING_SWEEP_THRESHOLD` 时：归集到关联交易账户。 | Funding Sweep。 |
| F5 | 当交易账户余额 < 该账户配置的阈值时：发送告警（如 Bark）。 | 可选。 |
| F6 | 在配置的北京时间：当所有账户“正常”时发送每日汇总。 | 可选。 |
| F7 | 资金账户查询失败不得阻塞自动平衡；对重复资金账户失败降低日志噪音（如连续 3 次后降为 WARNING）。 | 优雅降级。 |
| F8 | 从交易账户转到资金账户时，若可转余额不足：发送 Bark 告警（内容含账户名、方向、需要金额、可用金额）；**不中止流程**，告警后继续尝试转账（由 API 最终判定）。 | 在 `transfer_trading_to_funding` 中：转账前 `verify_transfer_balance` 失败或 API 返回余额不足时触发。 |
| F9 | 可转余额不足告警节流：相同内容（同一账户 + 同一方向，如 `Trading_8788:Trading→Funding`）在 **20 分钟内只发送一次**；冷却期内仅打 debug 日志不发送。 | 模块级 `_last_insufficient_balance_alert_time`，常量 `INSUFFICIENT_BALANCE_ALERT_COOLDOWN_SEC = 20*60`。 |

### 2.2 非功能需求

| 编号 | 需求 |
|------|------|
| NF1 | 日志中不输出密钥；尽量少输出个人可识别信息。 |
| NF2 | 单线程、单一轮询循环；支持信号（如 SIGINT/SIGTERM）优雅退出。 |
| NF3 | 通过 `GRVT_LOG_LEVEL` 可配置日志级别（如 INFO/DEBUG）。 |

---

## 3. 数据模型（内存）

### 3.1 AccountConfig（dataclass）

定义于 `grvt_balance_poll.py`（约第 38 行）。主要字段：

| 字段 | 类型 | 含义 |
|------|------|------|
| `name` | str | 显示/键名（如 Trading_8788、Funding_145b）。 |
| `account_type` | str | `"trading"` 或 `"funding"`。 |
| `api_key` | str | 该账户的 API Key。 |
| `account_id` | str | GRVT 账户 ID（内部）。 |
| `private_key` | str \| None | 转账与 SDK 认证必需。 |
| `env` | str | 如 prod、testnet。 |
| `threshold` | float \| None | 余额低于此值时告警。 |
| `related_trading_account_id` | str \| None | （资金账户）关联的交易账户 ID。 |
| `related_funding_account_id` | str \| None | （交易账户）关联的资金账户**地址**（以太坊），非内部 ID。 |
| `related_main_account_id` | str \| None | 转账 API 使用的主账户 ID。 |
| `funding_address` | str \| None | （资金账户）链上地址，用于外部转账；须在 GRVT Address Book 中。 |

### 3.2 主循环状态（每轮迭代）

- `account_balances`：账户名 → 余额（仅交易账户）。
- `account_summaries`：账户名 → 摘要字典（equity、available_balance、maintenance_margin），仅交易账户。
- `account_main_ids`：账户名 → main_account_id。
- `funding_account_balances`：账户名 → 余额（仅展示用）。
- `all_accounts_normal`：bool；任一**交易账户**查询失败则为 False（资金账户失败不置为 False）。
- `funding_account_failures`：账户名 → 连续失败次数（用于日志节流）。

### 3.3 可转余额不足告警（模块级）

- `_last_insufficient_balance_alert_time`：`Dict[str, float]`，key = `f"{account_name}:{direction}"`，value = 上次发送时间戳（`time.time()`）。用于 20 分钟节流。
- `INSUFFICIENT_BALANCE_ALERT_COOLDOWN_SEC`：常量 1200（20 分钟）。

---

## 4. 配置（.env）

### 4.1 全局

| 变量名 | 必填 | 默认 | 说明 |
|--------|------|------|------|
| `GRVT_POLL_INTERVAL` | 否 | 30 | 轮询间隔（秒）。 |
| `GRVT_BALANCE_THRESHOLD_PERCENT` | 否 | 43 | 自动平衡触发阈值（某账户占总资金比例低于此值）。 |
| `GRVT_BALANCE_TARGET_PERCENT` | 否 | 48 | 再平衡后的目标比例。 |
| `GRVT_FUNDING_SWEEP_THRESHOLD` | 否 | 100 | Funding Sweep 阈值（USDT）。 |
| `GRVT_LOG_LEVEL` | 否 | INFO | INFO 或 DEBUG。 |
| `GRVT_DAILY_SUMMARY_TIME` | 否 | - | 每日汇总发送时间（北京时间 HH:MM）。 |
| `GRVT_ALERT_DEVICE_KEY` | 否 | - | Bark 设备密钥。 |
| `GRVT_ENV` | 否 | prod | prod \| testnet \| staging \| dev。 |

### 4.2 按账户（X = 1, 2, …）

**交易账户（余额轮询至少 1 个；自动平衡需 2 个）：**

- 必填：`GRVT_TRADING_API_KEY_X`、`GRVT_TRADING_PRIVATE_KEY_X`、`GRVT_TRADING_ACCOUNT_ID_X`
- 可选：`GRVT_RELATED_FUNDING_ACCOUNT_ID_X`（资金账户**地址**）、`GRVT_RELATED_MAIN_ACCOUNT_ID_X`、`GRVT_THRESHOLD_X`、`GRVT_ENV_X`

**资金账户（可选，用于展示与转账）：**

- `GRVT_FUNDING_API_KEY_X`、`GRVT_FUNDING_PRIVATE_KEY_X`、`GRVT_FUNDING_ACCOUNT_ID_X`
- 可选：`GRVT_FUNDING_ACCOUNT_ADDRESS_X`（以太坊地址）、`GRVT_RELATED_TRADING_ACCOUNT_ID_X`、`GRVT_RELATED_MAIN_ACCOUNT_ID_X`、`GRVT_ENV_X`

**发现规则**：按 X 递增解析，直到某类账户的必填键缺失（如没有 `GRVT_TRADING_API_KEY_X`）为止。

---

## 5. 主流程

### 5.1 启动

1. 加载 `.env`（覆盖已有环境变量）。
2. `load_account_configs()`：解析所有 `GRVT_*_X` 得到 `List[AccountConfig]`，构建 `clients` 字典（name → {config, client}）。
3. 对每个账户通过 `build_client(config)` 构建一个 `GrvtRawSync`；可选做一次认证测试。
4. 进入主循环（轮询循环）。

### 5.2 轮询主循环（概要）

```
循环直到 stop_flag：
  重置：account_balances、account_summaries、account_main_ids、all_accounts_normal、funding_account_balances
  对 clients 中每个账户：
    若为 trading：
      ensure_authenticated()；aggregated_account_summary_v1()
      成功：写入 balance、summary、main_account_id；可选执行 Funding Sweep、阈值告警
      401/认证错误：reauthenticate_client() 并重试一次
    若为 funding：
      funding_account_summary_v1()
      成功：写入 funding_account_balances；重置该资金账户失败计数
      失败：funding_account_failures[name]++；按节流规则打日志（3 次后 WARNING，每 10 次打详情）；不设置 all_accounts_normal = False
  若恰好有 2 个交易账户且余额有效：
    校验余额（正数、最小阈值）；计算 transfer_info（改进版或基础版）
    若 transfer_info 且不在冷却期：
      执行转账前校验（金额、余额充足、main ID）
      transfer_between_trading_accounts_via_funding(...)
  若 all_accounts_normal 且到每日汇总时间：send_daily_summary()
  sleep(poll_interval)
```

### 5.3 自动平衡逻辑

- **输入**：两个交易账户名称及其余额（或 account_summaries，用于“改进版”逻辑）。
- **改进版**：使用 `check_and_balance_accounts_improved()`，结合 equity、available_balance、maintenance_margin；`calculate_safe_transfer_amount()` 避免过度转出。
- **基础版**：使用 `check_and_balance_accounts()`，仅用余额。
- **输出**：`transfer_info` = { from_account, to_account, amount, … } 或 None。
- **冷却**：同一方向转账键的冷却时间（如 30 秒）。
- **执行**：始终经资金路径 A_交易 → A_资金 → B_资金 → B_交易（`transfer_between_trading_accounts_via_funding`）。

### 5.4 Funding Sweep

- 在交易账户摘要查询成功后，若该账户配置了关联资金账户且设置了 `GRVT_FUNDING_SWEEP_THRESHOLD`：查询资金账户余额；若超过阈值，则调用归集逻辑（如 `sweep_funding_to_trading` 等）将资金划入该交易账户。

---

## 6. 关键函数索引

| 函数名 | 文件位置（约） | 作用 |
|--------|----------------|------|
| `load_account_configs` | ~245 | 解析 .env → List[AccountConfig]。 |
| `build_client` | ~56 | AccountConfig → GrvtRawSync。 |
| `ensure_authenticated` | ~181 | 检查认证；401/认证错误时重新认证。 |
| `reauthenticate_client` | ~159 | 认证失败后重建客户端。 |
| `get_account_summary` | ~571 | 交易账户摘要（equity、available、margin）。 |
| `check_and_balance_accounts` | ~925 | 基础余额检查（两个余额）。 |
| `check_and_balance_accounts_improved` | ~992 | 带安全约束的余额检查（使用 summaries）。 |
| `calculate_safe_transfer_amount` | ~697 | 根据 equity、available、maintenance_margin 计算安全转出额。 |
| `transfer_between_trading_accounts_via_funding` | ~1643 | 执行 A_交易→A_资金→B_资金→B_交易。 |
| `sweep_funding_to_trading` | ~733 | 将资金账户余额归集到关联交易账户。 |
| `send_alert` | ~369 | 发送阈值告警（如 Bark）。 |
| `send_insufficient_transfer_balance_alert` | ~401 | 发送可转余额不足告警（Trading→Funding）；同一账户+方向 20 分钟内只发一次。 |
| `send_daily_summary` | ~398 | 在配置时间发送每日汇总。 |
| `should_send_daily_summary` | ~432 | 判断是否到每日汇总时间（北京时间）。 |

---

## 7. 扩展点（二次开发）

- **新通知渠道**：在 `send_alert` / 每日汇总发送处替换或扩展 Bark；设备密钥等仍可从 .env 读取。
- **多于两个交易账户**：当前自动平衡仅支持“恰好两个”；可扩展为 N 账户或成对规则。
- **不同再平衡策略**：替换或包装 `check_and_balance_accounts` / `check_and_balance_accounts_improved`，实现自定义阈值、单笔最小/最大金额等。
- **配置来源**：可替换 `load_account_configs()`，从文件路径、远程配置或其它 schema 的 env 读取。
- **资金账户失败策略**：调整 `funding_account_failures` 的阈值（如 3、10）或增加熔断（N 次失败后 T 秒内跳过资金账户查询）。
- **转账前校验**：所有转账前校验均在主循环中、调用 `transfer_between_trading_accounts_via_funding` 之前；可在此处增加或放宽校验（如最大金额、最低余额）。
- **可转余额不足告警节流**：冷却时间由 `INSUFFICIENT_BALANCE_ALERT_COOLDOWN_SEC` 控制；可改为可配置（如从 .env 读取分钟数）。

---

## 8. 约束与不变式

- **交易账户**：余额轮询至少 1 个；自动平衡使用恰好 2 个。当前逻辑下超过 2 个不参与自动平衡。
- **转账路径**：交易账户 ↔ 交易账户 必须经 A_交易 → A_资金 → B_资金 → B_交易；两个交易账户均需配置关联资金账户与 main_account_id。
- **资金地址**：`GRVT_RELATED_FUNDING_ACCOUNT_ID_X` 必须是资金账户的**以太坊地址**（与 `GRVT_FUNDING_ACCOUNT_ADDRESS_*` 一致），不是内部账户 ID。
- **外部转账**：目标资金地址必须在 GRVT Address Book 中。
- **密钥**：仅存在于 `.env`；日志中不得完整输出 api_key 或 private_key。

---

## 9. 文件结构

```
GRVT/
├── grvt_balance_poll.py   # 主脚本
├── .env                   # 本地配置（gitignore）
├── .env.example           # 配置模板
├── README.md              # 用户文档
├── docs/
│   └── REQUIREMENTS.md    # 本文件
├── deploy.sh, install_service.sh, uninstall_service.sh, update_service.sh
└── grvt-balance-poll.service  # systemd 单元
```

---

## 10. 变更记录（供 AI 参考）

- **资金账户 401 处理**：资金账户错误不再设置 `all_accounts_normal`；连续失败记录在 `funding_account_failures`；连续 3 次后降低日志级别；每 10 次打一次详细日志。
- **自动平衡安全**：平衡前校验（≥2 个交易账户、余额为正、最小余额阈值）；转账前校验（余额有效、金额为正且上限合理、转出方余额充足、main_account_id 存在）。
- **转账前校验**：在调用 `transfer_between_trading_accounts_via_funding` 前显式校验，避免无效或过大转账。
- **可转余额不足告警（F8）**：从交易账户转到资金账户时，若 `verify_transfer_balance` 失败或 API 返回余额不足，调用 `send_insufficient_transfer_balance_alert` 发送 Bark；不中止，告警后继续执行/尝试转账。
- **可转余额不足告警节流（F9）**：相同内容（同一账户 + 同一方向）20 分钟内只发一次；使用 `_last_insufficient_balance_alert_time` 与 `INSUFFICIENT_BALANCE_ALERT_COOLDOWN_SEC = 1200`。
