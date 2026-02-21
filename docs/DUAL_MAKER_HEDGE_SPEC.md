# GRVT Dual Maker Hedge Spec (V1)

## 1. Goal
- 使用两交易账户（A/B）仅通过 maker 限价单进行对冲持仓管理。
- 保持对冲价格不亏损：
- A 买成交价为 P，则 B 对冲卖价必须 >= P。
- B 卖成交价为 P，则 A 对冲买价必须 <= P。
- 独立脚本运行，不改 `grvt_balance_poll.py` 主流程。

## 2. Hard Rules
- 下单固定为：`limit + post_only + GOOD_TILL_TIME`。
- 禁止主动吃单路径。
- 启动时必须接管已有仓位与已有挂单。
- 非策略订单保留，仅告警，不自动撤单。
- 测试/停机退出时支持自动清理策略挂单（可配置保留数量）。
- 风险策略为“告警不停机”：
- `maintenance_margin / equity >= 0.70` 告警。
- 未对冲时长 > 6h 即时告警 + 日报汇总。

## 3. Runtime Architecture
- 主循环：
1. 按需重建 A/B 认证状态（遇到认证错误时自动重建 client）
2. 拉取 positions/open-orders/account-summary
3. 更新 symbol 状态
4. 下单/冷却/告警决策
5. 每天（北京时间）发送 stuck 日报
- 核心状态对象：
- `SymbolConfig`
- `FillLot`
- `ManagedOrder`
- `SymbolState`
- `AlertState`

## 4. Config
- Env vars:
- `GRVT_HEDGE_LOOP_INTERVAL_SEC`（默认 `2`）
- `GRVT_HEDGE_ORDERBOOK_DEPTH`（默认 `10`）
- `GRVT_HEDGE_SDK_LOG_LEVEL`（默认 `ERROR`）
- `GRVT_HEDGE_SINGLE_ORDER_DIFF_THRESHOLD_USDT`（默认 `20`）
- `GRVT_HEDGE_MAX_RUNTIME_SEC`（默认 `0`，0=不自动停止）
- `GRVT_HEDGE_CANCEL_ON_STOP`（默认 `1`）
- `GRVT_HEDGE_STOP_KEEP_STRATEGY_ORDERS`（默认 `0`）
- `GRVT_HEDGE_POST_ONLY_MAX_RETRY`（默认 `5`）
- `GRVT_HEDGE_POST_ONLY_COOLDOWN_SEC`（默认 `300`）
- `GRVT_HEDGE_PARTIAL_FILL_TIMEOUT_SEC`（默认 `1800`）
- `GRVT_HEDGE_STUCK_HOURS`（默认 `6`）
- `GRVT_HEDGE_MMR_ALERT_THRESHOLD`（默认 `0.70`）
- `GRVT_HEDGE_SYMBOLS_FILE`（必填，JSON 文件路径）

### 4.1 Symbols file schema
参考：`config/hedge_symbols.example.json`

```json
[
  {
    "instrument": "BNB_USDT_Perp",
    "enabled": true,
    "order_notional_usdt": 1000,
    "imbalance_limit_usdt": 1000,
    "max_total_position_usdt": 30000,
    "min_total_position_usdt": 2000,
    "a_side_when_equal": "buy",
    "position_mode": "increase"
  }
]
```

字段说明：
- `instrument`: 标的 ID（推荐使用交易所返回的标准值，如 `*_Perp`；脚本会自动规范 `*_PERP`）
- `enabled`: 是否启用
- `order_notional_usdt`: 每次下单名义金额
- `imbalance_limit_usdt`: 允许失衡阈值
- `max_total_position_usdt`: 增仓模式的总持仓上限（|A|+|B|）
- `min_total_position_usdt`: 减仓模式的总持仓下限（|A|+|B|）
- `a_side_when_equal`: 仓位相等时 A 的基准方向
- `position_mode`: `increase`/`decrease`

## 5. Pricing and Size Rules
- 行情输入：
- `tick_size`, `min_size`, `base_decimals` from `get_instrument_v1`
- `bid1/ask1` from `orderbook_levels_v1(depth=10)`（可配置，默认 10）
- 定价：
- sell: `max(ask1, guard_price)`
- buy: `min(bid1, guard_price)`
- 价格精度：
- buy 向下取整到 tick
- sell 向上取整到 tick
- 数量：
- `size` 按 `min_size` 步长向下取整（同时满足 `base_decimals` 精度），且 `size >= min_size`

## 6. Hedge Matching
- 成交通过 `ManagedOrder` 的 traded-size 增量进入台账。
- 部分成交规则：
- 部分成交且订单仍 OPEN 时，最长等待 1800s。
- 超时后按已成交增量入账。
- `FillLot` 匹配规则：
- 必须跨账户 + 反向 side。
- 匹配时执行价格保护（sell >= buy_guard，buy <= sell_guard）。
- 未匹配剩余量继续留在队列。

## 7. Execution State Machine
- `|A| == |B|`：
- 可各挂一单（每账户每标的活动单 < 2）
- `position_mode=increase`：A 用 `a_side_when_equal`，B 取反
- `position_mode=decrease`：A 用 `a_side_when_equal` 的反向，B 再取反
- `position_mode=decrease` 且 A/B 该标的都为 0 时，不再开新单
- `|A| != |B|`：
- 仅小仓位账户允许新增单
- side/guard 优先由未匹配 lot 决定，不足时由大仓方向+entry_price 回退
- 失衡控制：
- `gap = large_abs - (small_abs + hedge_open/2)`
- 下单名义：`min(order_notional_usdt, 2*gap)`（支持最后一档缩量）
- 低差额限单：
- 当 `|abs_a - abs_b| < GRVT_HEDGE_SINGLE_ORDER_DIFF_THRESHOLD_USDT`，每账户该标的最多 1 个策略挂单（A 最多 1，B 最多 1）。

## 8. Position Limits
- 每账户每标的活动单上限：2
- 低差额限单命中时，每账户每标的活动单上限降为 1
- `position_mode=increase`：
- 达到上限时，阻止“扩张型”挂单；修复单仅在不突破上限时允许
- `position_mode=decrease`：
- 达到下限时，阻止“继续缩减型”挂单；修复单仅在不跌破下限时允许

## 9. Startup Reconcile
- 已有仓位：用 `entry_price` + abs notional 生成 synthetic lots。
- 已有挂单：
- 策略单接管并继续管理
- 非策略单保留并告警
- 订单 ID 兼容：
- 下单 `client_order_id` 使用数值型，避免交易所拒绝。
- 若 create 返回临时 `order_id`（如 `0x00`），后续通过 `client_order_id` 与真实订单 ID 对齐。

## 10. Alerts
- 通道：仅 Telegram 网关（`CHAT_ID` + `API_KEY`）
- 告警去重：按 key + cooldown
- 即时告警：
- API 异常
- MMR 超阈值
- post-only 重试耗尽（进入冷却）
- 未对冲 > 6h
- 非策略订单冲突
- 日报：
- 每天汇总仍 >6h 未对冲的标的

## 11. Stop Behavior
- 支持 `GRVT_HEDGE_MAX_RUNTIME_SEC` 到时自动停止。
- 停止时若 `GRVT_HEDGE_CANCEL_ON_STOP=1`，自动清理策略挂单。
- 停止清理可用 `GRVT_HEDGE_STOP_KEEP_STRATEGY_ORDERS` 配置每账户每标的保留数量。
