# GRVT 双账户 Maker 对冲需求总览

## 1. 文档说明
- 该文件是需求索引，不承载全部细节。
- 需求已拆分为两个版本：
- 产品视角：便于业务确认、验收和优先级管理。
- 工程视角：便于开发、测试、审计直接落地。

## 2. 阅读顺序
1. 先读产品需求：确认“做什么、为什么做、验收看什么”。
2. 再读工程需求：确认“怎么做、边界怎么处理、如何测试与告警”。

## 3. 需求文档入口
- 产品需求：`docs/DUAL_MAKER_HEDGE_REQUIREMENTS_PRODUCT.md`
- 工程需求：`docs/DUAL_MAKER_HEDGE_REQUIREMENTS_ENGINEERING.md`

## 4. 关联文档
- 策略规格：`docs/DUAL_MAKER_HEDGE_SPEC.md`
- 运维手册：`docs/DUAL_MAKER_HEDGE_RUNBOOK.md`
- 审计报告：`docs/DUAL_MAKER_HEDGE_AUDIT.md`
- 标的配置模板：`config/hedge_symbols.example.json`

## 5. 当前锁定范围（摘要）
- 全程 maker 限价单（post-only），拒绝主动吃单。
- 对冲按一一对应成交价保护，不亏损口径按成交保护价定义。
- 每标的可独立配置 `increase` / `decrease`。
- 增仓受 `max_total_position_usdt` 限制，减仓受 `min_total_position_usdt` 限制。
- 当某标的持仓差 < 20U 时，每账户该标的最多 1 个策略挂单（A 最多 1，B 最多 1）。
- 启动接管已有仓位与订单；非策略订单保留并告警。
- 支持自动停机与停机策略单清理（可配置保留数量）。
- 风控为告警不停机：`MMR >= 70%`、未对冲超过 6h、post-only 冷却告警。
