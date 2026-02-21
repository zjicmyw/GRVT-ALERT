# GRVT 双账户 Maker 对冲引擎需求文档（工程视角）

## 1. 文档定位
- 本文档是工程实现基线，覆盖我们已确认的全部规则、边界和异常处理约束。
- 目标：开发、测试、审计三方使用同一口径，避免实现偏差。

## 2. 背景与目标
- 背景：GRVT maker 成本低、taker 成本高，策略必须全程 maker 化。
- 目标：在 A/B 双账户下，以对冲方式管理持仓量，同时保证成交价约束、不主动吃单、风险可告警。

## 3. 已锁定业务口径（讨论结论）
1. 只允许 maker 限价单：`post_only=true`，拒绝主动吃单。
2. 按标的支持 `increase`（增仓）/`decrease`（减仓）两种模式。
3. 不亏损对冲按成交保护价定义：
- A 买成交价为 `P`，B 的对应卖价必须 `>= P`。
- B 卖成交价为 `P`，A 的对应买价必须 `<= P`。
4. 启动时接管已有仓位和已有订单（A/B 可能已有历史状态）。
5. 非策略订单保留并告警，不自动撤销，不纳入策略计算口径。
6. 风控动作为“告警不停机”。
7. 告警阈值固定：
- `maintenance_margin / equity >= 0.70` 触发 MMR 告警。
- 未完成对冲超过 6 小时触发 stuck 告警并进入日报。
8. 部分成交等待 30 分钟，超时后按已成交增量继续对冲。

## 4. 作用范围
- 脚本：`grvt_dual_maker_hedge.py`（独立入口，不影响 `grvt_balance_poll.py` 现有能力）。
- 文档：规格、运维、审计、需求（产品/工程双版本）。
- 配置：`.env` + `GRVT_HEDGE_SYMBOLS_FILE`（UTF-8 JSON）。

## 5. 非目标（V1）
- 不做 UI。
- 不把 funding fee 纳入“无损”判定。
- 不加入额外利润 buffer（不额外加 bps）。
- 不做强制停机/强平，仅告警。
- 不为追成交主动撤旧挂新。

## 6. 配置与数据模型

### 6.1 环境变量
- `GRVT_HEDGE_LOOP_INTERVAL_SEC`：主循环间隔（默认 2）。
- `GRVT_HEDGE_ORDERBOOK_DEPTH`：盘口查询深度（默认 10）。
- `GRVT_HEDGE_SDK_LOG_LEVEL`：SDK 内部日志级别（默认 ERROR）。
- `GRVT_HEDGE_SINGLE_ORDER_DIFF_THRESHOLD_USDT`：低差额限单阈值（默认 20）。
- `GRVT_HEDGE_MAX_RUNTIME_SEC`：最大运行时长秒数（默认 0，不自动停）。
- `GRVT_HEDGE_CANCEL_ON_STOP`：停止时是否清理策略单（默认 1）。
- `GRVT_HEDGE_STOP_KEEP_STRATEGY_ORDERS`：停止清理时每账户每标的保留策略单数量（默认 0）。
- `GRVT_HEDGE_POST_ONLY_MAX_RETRY`：post-only 单轮最大重试（默认 5）。
- `GRVT_HEDGE_POST_ONLY_COOLDOWN_SEC`：重试耗尽冷却秒数（默认 300）。
- `GRVT_HEDGE_PARTIAL_FILL_TIMEOUT_SEC`：部分成交超时秒数（默认 1800）。
- `GRVT_HEDGE_STUCK_HOURS`：未对冲超时小时（默认 6）。
- `GRVT_HEDGE_MMR_ALERT_THRESHOLD`：MMR 告警阈值（默认 0.70）。
- `GRVT_HEDGE_SYMBOLS_FILE`：标的 JSON 文件路径（默认 `config/hedge_symbols.json`）。

### 6.2 标的配置（JSON）
每个标的字段：
- `instrument`：标的 ID。
- `enabled`：是否启用。
- `order_notional_usdt`：每档名义金额。
- `imbalance_limit_usdt`：允许失衡阈值（默认 1000）。
- `max_total_position_usdt`：增仓模式总持仓上限。
- `min_total_position_usdt`：减仓模式总持仓下限。
- `a_side_when_equal`：仓位相等时 A 的基准方向（`buy`/`sell`）。
- `position_mode`：`increase` 或 `decrease`。

### 6.3 核心内部类型
- `SymbolConfig`
- `FillLot`
- `ManagedOrder`
- `SymbolState`
- `AlertState`

## 7. 订单与定价规则

### 7.1 强制 maker
所有策略下单必须满足：
- `is_market = False`
- `post_only = True`
- `time_in_force = GOOD_TILL_TIME`

### 7.2 价格保护规则
- 卖单价格：`sell_price = max(ask1, guard_price)`。
- 买单价格：`buy_price = min(bid1, guard_price)`。
- `guard_price` 来自待对冲 lot 的保护成交价。

### 7.3 精度处理
- 价格按 `tick_size`：
- 买价向下取整。
- 卖价向上取整。
- 数量按 `min_size` 步长向下取整，并满足 `base_decimals` 精度约束。

## 8. 仓位、失衡与下单控制

### 8.1 仓位口径
- 每账户每标的仓位统一换算为 USDT 名义绝对值：`abs_notional`。

### 8.2 失衡口径
- 使用实现口径：
- `gap = large_abs - (small_abs + hedge_open_orders_notional / 2)`。
- `gap > 0` 表示小仓位侧仍需补单。

### 8.3 失衡约束
- 目标是维持失衡在 `imbalance_limit_usdt` 以内（常用为 1000U）。
- 仓位不平衡时，仅小仓位账户新增单；大仓位账户不加剧失衡。

### 8.4 每账户活动单上限
- 每账户每标的最多 2 个活动策略单。
- 超限不再下新单，并触发告警。

### 8.5 低差额限单
- 当某标的 `|abs_a - abs_b| < GRVT_HEDGE_SINGLE_ORDER_DIFF_THRESHOLD_USDT` 时：
- A 账户该标的最多 1 个策略活动单。
- B 账户该标的最多 1 个策略活动单。
- 若超限，优先撤销该账户最早策略单，保留较新的单。
- 当 `|abs_a - abs_b| >=` 该阈值时，恢复每账户最多 2 单；小仓位账户会优先补满到 2 单，再进入常规失衡阈值抑制逻辑。

### 8.6 最后一档缩量
- 补单名义：`min(order_notional_usdt, 2 * gap)`。
- 下单前按边界约束裁剪，裁剪后低于最小下单则跳过。

## 9. 增仓/减仓模式行为

### 9.1 `increase`
- 仓位相等时双边同时挂单：
- A 按 `a_side_when_equal`。
- B 挂反向。
- 下单前检查 `|A| + |B| < max_total_position_usdt`，防止越界。

### 9.2 `decrease`
- 仓位相等时优先选择“减少当前仓位”的方向。
- 若仓位结构异常无法判断，回退到基准方向并告警。
- 当总持仓到达 `min_total_position_usdt`，禁止继续缩减方向的新单。
- 当 A/B 均近似零仓位，不再开新单。

### 9.3 边界动作
- 不允许“越界方向”下单。
- 允许“不越界”的修复性对冲单继续执行。

## 10. 成交台账与对冲配对

### 10.1 FillLot 队列
- 已成交量按 lot 入账，记录账户、方向、数量、保护价、时间戳。
- 对冲匹配采用跨账户反向配对，一一对应消耗 lot。

### 10.2 部分成交
- 订单处于部分成交且仍 OPEN 时先等待。
- 超过 `GRVT_HEDGE_PARTIAL_FILL_TIMEOUT_SEC` 后，按已成交增量入账。

## 11. 启动接管

### 11.1 已有仓位
- 读取 A/B 当前仓位。
- 使用 `entry_price` 生成 synthetic lot，纳入后续配对。

### 11.2 已有订单
- 识别策略订单并接管管理。
- 非策略订单：
- 保留。
- 告警提示。
- 不参与策略活动单计数与失衡计算。
- 兼容临时订单 ID（如 `0x00`）与真实订单 ID 的后续对齐。

## 12. 风控与告警

### 12.1 MMR
- 计算 `maintenance_margin / equity`。
- `>= 0.70` 即时告警，带去重冷却。

### 12.2 Stuck
- 任一标的存在未对冲 lot 持续超过 6 小时：
- 立即告警。
- 加入每日汇总。

### 12.3 Post-only 失败
- 同一轮最多重试 5 次。
- 每次重试刷新盘口并重算价格，仍必须满足保护价。
- 重试耗尽后进入 300 秒冷却并告警。

### 12.4 告警通道
- 仅使用本地 Telegram 网关（`CHAT_ID` + `API_KEY`）。

## 13. 停机与清理
- 收到 `SIGINT/SIGTERM` 或达到 `GRVT_HEDGE_MAX_RUNTIME_SEC` 后停止主循环。
- 若 `GRVT_HEDGE_CANCEL_ON_STOP=1`，停止阶段自动清理策略挂单。
- 清理保留数量由 `GRVT_HEDGE_STOP_KEEP_STRATEGY_ORDERS` 控制（按每账户每标的生效）。

## 14. 运行状态机
1. 加载 `.env` 和 symbols 文件。
2. 初始化 A/B 客户端与标的状态。
3. 执行启动接管（仓位 + 订单）。
4. 主循环：
- 拉取行情、仓位、订单。
- 更新成交增量与 lot 队列。
- 计算失衡和边界。
- 生成并提交 post-only 策略单（含重试/冷却）。
- 执行告警与日报聚合。
- 退出时执行策略单清理（按配置）。

## 15. 测试与验收清单
1. 空仓启动时，双边都能挂出 post-only 单。
2. A 先买成交后，B 对冲卖价始终不低于 A 买价保护线。
3. B 先卖成交后，A 对冲买价始终不高于 B 卖价保护线。
4. 仓位相等时，按 `a_side_when_equal` 与 `position_mode` 生成方向。
5. 仓位不等时，仅小仓位账户新增单。
6. 每账户每标的活动策略单超过 2 时被阻止并告警。
7. 部分成交 30 分钟内等待，超时后按增量入账。
8. 最后一档缩量能把差额收敛到阈值内。
9. `MMR >= 0.70` 触发即时告警。
10. 未对冲超过 6 小时触发即时告警并进入日报。
11. 启动接管已有仓位/订单成功。
12. 非策略订单不被撤销，且产生冲突告警。
13. post-only 连续拒单后进入冷却并能自动恢复。
14. 多标的并行运行时状态互不污染。
15. 当 `|abs_a-abs_b| < 20U` 时，每账户最多 1 单（A 最多 1，B 最多 1）。
16. 设置自动停机后，退出阶段会按配置清理策略挂单。

## 16. 典型业务场景（讨论原例映射）

### 16.1 增仓场景
1. A 在买一挂买单（例：1002，1000U），B 在卖一挂卖单（例：1002.1，1000U）。
2. 若 A 先成交，A 持多仓、B 可能空仓；B 保留老卖单并新增新的卖一档（例如 1001.1）。
3. B 新卖单成交后，轮到 A 侧补单，持续满足“一一对应成交保护”。

### 16.2 减仓场景
1. 标的配置 `position_mode=decrease`。
2. 优先沿减少现有仓位方向挂单。
3. 到 `min_total_position_usdt` 后停止继续缩减型下单。

## 17. 交付物映射
- 需求总览：`docs/DUAL_MAKER_HEDGE_REQUIREMENTS.md`
- 产品需求：`docs/DUAL_MAKER_HEDGE_REQUIREMENTS_PRODUCT.md`
- 工程需求：`docs/DUAL_MAKER_HEDGE_REQUIREMENTS_ENGINEERING.md`
- 策略规格：`docs/DUAL_MAKER_HEDGE_SPEC.md`
- 运维手册：`docs/DUAL_MAKER_HEDGE_RUNBOOK.md`
- 审计报告：`docs/DUAL_MAKER_HEDGE_AUDIT.md`
