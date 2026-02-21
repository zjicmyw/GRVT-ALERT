# GRVT Dual Maker Hedge Runbook

## 1. Preconditions
- `.env` 中已配置两套交易账户：
- `GRVT_TRADING_API_KEY_1/2`
- `GRVT_TRADING_PRIVATE_KEY_1/2`
- `GRVT_TRADING_ACCOUNT_ID_1/2`
- 告警通道（必填）：
- Telegram 网关: `CHAT_ID` + `API_KEY`

## 2. Required Strategy Config
- 在 `.env` 增加：`GRVT_HEDGE_SYMBOLS_FILE`。
- 示例：
```env
GRVT_HEDGE_LOOP_INTERVAL_SEC=2
GRVT_HEDGE_ORDERBOOK_DEPTH=10
GRVT_HEDGE_SDK_LOG_LEVEL=ERROR
GRVT_HEDGE_SINGLE_ORDER_DIFF_THRESHOLD_USDT=20
GRVT_HEDGE_MAX_RUNTIME_SEC=0
GRVT_HEDGE_CANCEL_ON_STOP=1
GRVT_HEDGE_STOP_KEEP_STRATEGY_ORDERS=0
GRVT_HEDGE_POST_ONLY_MAX_RETRY=5
GRVT_HEDGE_POST_ONLY_COOLDOWN_SEC=300
GRVT_HEDGE_PARTIAL_FILL_TIMEOUT_SEC=1800
GRVT_HEDGE_STUCK_HOURS=6
GRVT_HEDGE_MMR_ALERT_THRESHOLD=0.70
GRVT_HEDGE_SYMBOLS_FILE=config/hedge_symbols.json
```

- 标的配置文件参考：`config/hedge_symbols.example.json`
- 关键字段：
- `position_mode`:
- `increase`：增加持仓（受 `max_total_position_usdt` 限制）
- `decrease`：减少持仓（受 `min_total_position_usdt` 限制）
- `instrument`：推荐直接使用交易所标准值（如 `LTC_USDT_Perp`），脚本也支持 `*_PERP` 自动规范化。

## 3. Start
```powershell
python grvt_dual_maker_hedge.py
```

## 4. Test Stop (Recommended)
用于短测自动停机并清理策略挂单：
```powershell
$env:GRVT_HEDGE_MAX_RUNTIME_SEC='600'
$env:GRVT_HEDGE_CANCEL_ON_STOP='1'
$env:GRVT_HEDGE_STOP_KEEP_STRATEGY_ORDERS='0'
python grvt_dual_maker_hedge.py
```

## 5. Gray Rollout
1. 先开 1 个标的，`order_notional_usdt` 用小值。
2. 观察 30-60 分钟：
- 下单成功率
- post-only 拒单率
- 对冲持续时长
- MMR 告警
3. 稳定后逐步增加标的。

## 6. Operational Checks
- 日志文件：`logs/grvt_dual_maker_hedge.log`
- 关键日志：
- `Placed A/B buy/sell ...`
- `per_account_cap_when_diff<...=>1`（低差额每账户限1单）
- `Cancelled extra strategy order due to low diff account cap`
- `MMR ALERT`
- `unhedged>6h`
- `cooldown`
- `non-strategy order detected`
- `Stop cleanup finished`

## 7. Common Issues
- `Symbols config file not found`
- 检查 `GRVT_HEDGE_SYMBOLS_FILE` 路径是否正确（相对路径以项目根目录为基准）。
- `Invalid symbols config JSON`
- 检查 JSON 格式与 UTF-8 编码。
- post-only 高频拒单
- 正常现象，策略会重试，达到上限后进入冷却。
- `Client Order ID should be supplied`
- 已修复为数值型 client_order_id；若出现，先确认是否运行的是最新脚本版本。
- `Order size too granular`
- 已修复为按 `min_size` 步长取整；若出现，检查 `order_notional_usdt` 是否过小。
- 非策略订单冲突
- 策略不会自动撤掉人工单，只会告警。

## 8. Safety Behavior
- 该引擎按需求为“告警不停机”策略。
- 风险告警触发后继续运行，不自动停机。

## 9. Rollback
- 停止进程（`Ctrl+C`）。
- 仅运行旧余额脚本：
```powershell
python grvt_balance_poll.py
```
- 不影响现有 `grvt_balance_poll.py` 逻辑。
