# SQLite 数据接入与 DBeaver 查看

表关系、完整字段含义及因子/实验 JSON 结构见 [数据库设计说明](数据库设计说明.md)，可执行关联示例见 [数据库关系查询.sql](数据库关系查询.sql)。

已在原项目内将六类期货原始数据迁入 SQLite。数据库负责原始行情、增量覆盖和任务状态；Parquet 保存不可变研究快照及实验输出。后续下载直接入库，旧缓存文件仅保留作迁移来源，不再更新。

## 连接 DBeaver

1. 安装 DBeaver Community。
2. 新建数据库连接，选择 **SQLite**。
3. 数据库文件选择：

   `/Users/lucienzeng/Documents/ChatGPT/期货因子挖掘/AlphaGPT_Tushare/runtime/research.sqlite`

4. 若提示缺少 SQLite 驱动，可按 DBeaver 提示下载。无需主机、端口或数据库账号密码。
5. 建议在连接设置中开启 **Read-only connection**；保持自动提交，刷新查询即可看到程序新提交的数据。
6. 展开连接的 **Views / 视图**，双击下列中文视图，在 Data / 数据页浏览。数据库在程序关闭后仍可查看。

DBeaver 文档：[SQLite连接](https://dbeaver.com/docs/dbeaver/Database-driver-SQLite/)、[只读设置](https://dbeaver.com/docs/dbeaver/Managing-security-restrictions-for-database-connection/)。

## 优先浏览这些中文视图

| 视图 | 用途 |
| --- | --- |
| 沪铜_月份合约行情 | 真实月份 OHLC、结算、量、持仓、每手数量和到期日 |
| 沪铜_主力映射 | 主连代码每天对应的真实月份合约 |
| 沪铜_主连未复权行情 | 映射与真实合约行情关联后的原始主连价格，明确标为未复权 |
| 期货_合约信息 | 合约列表、上市、最后交易日与交割日 |
| 期货_交易日历 | 日历日期、是否交易、前交易日 |
| 期货_涨跌停与保证金 | 原始涨跌停和最低保证金百分数 |
| 期货_结算参数 | 原始结算、手续费及保证金参数，不猜测缺失口径 |
| 期货_数据覆盖 | 各接口/合约的已入库行数、最早最晚日期、本地入库时间 |
| 期货_同步清单 | 已存在数据的逐日覆盖标记 |
| 期货_数据缺口 | 主力映射缺行情、月份日线缺涨跌停或结算参数的关联缺口 |

视图中的“本地入库时间”是写入本地数据库的时间。迁移导入时为迁移时间，不代表供应商历史发布时间。覆盖表的最早/最晚日期不等于中间无缺口；关联缺口视图按接口记录，同一天可能有多个缺口。它检查已入库表之间的关联，不代表已经全面扫描所有未下载的历史区间。

原始业务表位于 Tables / 表：

| 表 | Tushare接口 | 唯一主键 |
| --- | --- | --- |
| contracts | fut_basic | ts_code |
| trade_calendar | fut_trade_cal | exchange, cal_date |
| daily_bars | fut_daily | ts_code, trade_date |
| main_mapping | fut_mapping | ts_code, trade_date |
| price_limits | ft_limit | ts_code, trade_date |
| settlement_params | fut_settle | ts_code, trade_date |

价格元/吨、量与持仓手、成交额万元，日期为 ISO 文本 `YYYY-MM-DD`，可直接按范围筛选。供应商字段为独立的普通列，不塞进一大段JSON。`_scope`、`_updated_at`、`_source_task` 为内部来源追踪字段；`market_catalog` 保留列顺序/类型以保持旧计算一致。

原始行情仍仅覆盖所选区间和预热范围里曾为主力的月份合约；合约元数据会包含更多CU代码。主连映射与月份合约始终分表。数据库里的主连视图未复权，研究连续价格仍由已有因子模块按历史可得价格衔接；不要直接用原始主连换月跳空计算策略收益。

## 下载缺口记录

结算参数正常响应但缺少数据时，不再阻断其他合约同步。界面“下载缺口记录”及中文视图 `期货_下载缺口记录` 展示每个合约、交易日的原因、状态、检查次数、任务与补齐时间；原表为 `data_gaps`。缺失日期不写覆盖清单，后续同步继续重试，补齐后自动标为 resolved。完整警告保存到任务 JSONL、events 和 `runtime/logs/server.log`。权限、网络及格式错误仍会报错。

固定成本模式可回测；历史手续费模式在实际成交日缺参数时仍严格失败。快照质量包含缺失结算参数行数，不把不完整参数伪装为完整数据。

## 数据同步与回测

- 每个分段按合约和日期 UPSERT，唯一键防止重复行。
- 行情、覆盖标记和修复检查点同一事务提交；任何一步失败，整段回滚。
- 原始行不存在时，即使残留覆盖标志也会补缺，空响应不标成功。
- WAL 模式支持应用写入时另一个客户端读取；单写入执行器保持不变。
- 同步成功后，从主库生成冻结的 Parquet 快照；旧实验继续读取原快照，修复原始数据不会改旧结果。
- 原始SQL表可包含失败下载保存的部分分段，研究界面只选择成功生成的快照。

研究界面“数据同步”页面现在显示数据库文件路径、业务表汇总、逐合约覆盖、缺口、主力映射和SQL原始行情预览。与DBeaver读取的是同一个数据库。

常用只读查询见 [dbeaver_queries.sql](dbeaver_queries.sql)。

## 迁移与运行日志

首次启动界面或首次同步时自动迁移，也可在关闭界面服务后运行：

```bash
.venv/bin/python -m alphagpt.research.cli migrate-data
```

迁移先用 SQLite backup API 备份数据库，并复制旧缓存到 `runtime/backups/<迁移ID>/`。在单一事务中导入所有原始表，逐文件对照列、类型、值，再写完成标记；失败回滚，可修复后重试。旧缓存文件保留但不再作为运行时数据来源，完成标记防止重复导入覆盖新数据。

本次迁移：`sqlite_migration_20261018_123106_fce5737d`。78个旧文件、16,975条记录，每份均通过精确对照，外部请求0次。

| 表 | 迁移后行数 |
| --- | ---: |
| contracts | 392 |
| trade_calendar | 1,271 |
| daily_bars | 4,839 |
| main_mapping | 840 |
| price_limits | 4,839 |
| settlement_params | 4,794 |

备份：`runtime/backups/sqlite_migration_20261018_123106_fce5737d/`。

此次也保留了之前扩展下载至2026年的未完成分段，关联缺口视图当前400条，其中主力日线355条、结算参数45条。旧任务曾在 `fut_settle CU2607.SHF` 空响应处失败，这些缺口是原有下载状态，不是迁移丢失；所选2024年成功快照仍完整可复现。本次没有自动扩大下载或隐藏失败。

验证记录：

- `runtime/verification/sqlite_migration_20261018_123106_fce5737d.json`：逐文件迁移对照、SHA256与备份位置。
- `runtime/verification/sqlite_migration_command.log`：迁移命令完整输出。
- `runtime/verification/sqlite_acceptance_run_20261018_123351_5927fea7.json`：真实数据端到端验证。
- `runtime/verification/sqlite_acceptance_command.log`：验收命令完整输出。

验收实际阻断了外部API及旧缓存Parquet读取：2024年重复同步0次请求，生成同一快照 `cu_6bdd3416eb40e69dba65`；SQL取数与冻结快照逐字段、因子值一致；既有实验 `eval_20261018_014309_dcf7b4c4` 的逐日账本和成交完全一致。111份旧快照和实验文件未改变，SQLite完整性检查为ok。

最新验收报告为 `runtime/verification/sqlite_acceptance_latest.json`，原命名报告保留。

31项测试全部通过（`runtime/verification/20261018_123838_tests.log`，对应JUnit同目录）。新增测试覆盖迁移精确性/幂等/备份、失败回滚重试、行情与覆盖原子提交、唯一键更新、只读浏览与写入并发、日期范围、部分列更新及错误合约不能标记覆盖。运行 `scripts/verify.py` 可获得完整测试日志与JUnit。

![SQLite数据覆盖界面](../runtime/verification/sqlite_data_ui.png)
![SQLite原始行情预览](../runtime/verification/sqlite_rows_ui.png)

## 2026-10-18 结算参数缺口修复验收

已恢复原失败任务 `sync_20261018_134012_b6e206b4`，2025-01-01 至 2026-10-16 同步成功，快照 `cu_415ca1b7e721bf6846ad`，6,062 行月份行情，新增请求 27 次，跳过已覆盖日期 17,531 个（按接口分别计数）。

`data_gaps` 保留 152 条结算参数缺口：CU2607 6 条、CU2608 29 条、CU2609 / CU2610 / CU2611 各 39 条。任务保存 7 次分段缺口警告，控制台服务日志与 JSONL 同步留存；检查确认这些 open 缺口没有进入 coverage。部分结算参数缺失不再阻断数据快照，历史手续费回测仍严格检查。

- 真实数据同步验收报告：`runtime/verification/settlement_gap_real_acceptance.json`（此处仅真实数据同步，未执行实盘交易）。
- 完整原任务事件日志：`runtime/logs/sync_20261018_134012_b6e206b4.jsonl`，含原失败及恢复过程。
- 服务控制台：`runtime/logs/server.log`。
- 35 项测试通过：`runtime/verification/20261018_135405_tests.log`。
- 新增测试覆盖整段空、部分空、重复尝试、不误标覆盖、补齐自动关闭、全参数缺失仍生成快照，以及固定费用可回测 / 历史费用拒绝缺失。
