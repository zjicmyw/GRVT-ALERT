# Dual Maker Hedge 审计报告（最新版）

## 审计范围
- 代码：`grvt_dual_maker_hedge.py`
- 文档：`README.md`、`docs/DUAL_MAKER_HEDGE_SPEC.md`、`docs/DUAL_MAKER_HEDGE_RUNBOOK.md`、`docs/DUAL_MAKER_HEDGE_REQUIREMENTS*.md`、`.env.example`

## 审计方法
- 静态代码审计（下单、风控、告警、订单接管、退出清理路径）。
- 行为回放（低差额限单、停机清理、接管已有单、非策略单混入）。
- 语法校验：`python -m py_compile grvt_dual_maker_hedge.py`

## 本轮已确认修复
1. 盘口查询 `depth` 非法问题修复：
- 使用可配置 `GRVT_HEDGE_ORDERBOOK_DEPTH`，默认 10（兼容交易所限制）。

2. 下单签名崩溃修复：
- 为签名填充有效 `expiration` 与 `nonce`，修复 `int('')` 异常。

3. `client_order_id` 兼容修复：
- 使用数值型 `client_order_id`，修复 “Client Order ID should be supplied” 拒单。

4. 数量粒度修复：
- 按 `min_size` 步长取整，修复 “Order size too granular”。

5. 低差额限单规则落地：
- 当 `|abs_a-abs_b| < GRVT_HEDGE_SINGLE_ORDER_DIFF_THRESHOLD_USDT` 时，每账户该标的最多 1 单（A 最多 1，B 最多 1）。

6. 停机清理能力落地：
- 支持 `max_runtime` 自动停机。
- 退出时可自动清理策略挂单，并按配置保留数量。

7. 临时订单 ID 兼容修复：
- 兼容 `0x00` 等临时 `order_id`，通过 `client_order_id` 对齐真实订单 ID，避免误撤与重复报错。

8. 告警通道口径统一：
- 对冲引擎告警仅走 Telegram（`CHAT_ID` + `API_KEY`）。

## 风险分级结论

### Critical
- 未发现。

### High
- 未发现。

### Medium
1. 边界裁剪仍基于名义金额近似。
- 在高波动下，成交后可能出现短时边界轻微偏离。
- 建议后续增加“成交后二次校验 + 修正单”。

### Low
1. 非策略订单告警仍按 symbol 粒度去重。
- 同一 symbol 多个人工单可能只提示一次。
- 建议后续按 `order_id` 细化告警去重键。

## 文档一致性结论
- README、SPEC、RUNBOOK、需求文档已同步本轮实现与修复。
- 配置项与行为口径保持一致（含低差额限单、自动停机、退出清理、SDK 日志级别）。

## 上线前建议验证
1. 低差额场景验证：`|abs_a-abs_b| < 20U` 时 A/B 是否各最多 1 单。
2. 停机清理验证：`GRVT_HEDGE_CANCEL_ON_STOP=1` 时策略单是否按保留数正确清理。
3. 接管验证：启动前存在策略单/人工单混合时，策略是否仅纳管策略单。
4. 风控验证：MMR 告警、stuck>6h 告警与日报链路。
