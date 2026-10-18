-- 沪铜 MVP 数据库关系查询；全部为只读 SELECT。
-- 1. 同一天的主连、真实合约、行情、每手吨数、参数，一行对照。
SELECT m.ts_code AS 主连代码, m.trade_date AS 交易日,
       m.mapping_ts_code AS 实际月份合约, c.name AS 合约名称,
       c.per_unit AS 每手吨数, c.delist_date AS 最后交易日,
       b.open AS 开盘价, b.close AS 收盘价, b.settle AS 行情结算价,
       b.vol AS 成交量_手, b.oi AS 持仓量_手,
       p.up_limit AS 涨停价, p.down_limit AS 跌停价,
       p.m_ratio AS 最低保证金率_百分数,
       s.settle AS 参数结算价, s.trading_fee_rate AS 原始手续费率,
       s.trading_fee AS 原始手续费参数
FROM main_mapping m
LEFT JOIN contracts c ON c.ts_code=m.mapping_ts_code
LEFT JOIN daily_bars b ON b.ts_code=m.mapping_ts_code AND b.trade_date=m.trade_date
LEFT JOIN price_limits p ON p.ts_code=m.mapping_ts_code AND p.trade_date=m.trade_date
LEFT JOIN settlement_params s ON s.ts_code=m.mapping_ts_code AND s.trade_date=m.trade_date
WHERE m.ts_code='CU.SHF' AND m.trade_date='2024-12-31';

-- 2. 查看某真实月份合约的一段行情。
SELECT * FROM daily_bars
WHERE ts_code='CU2502.SHF' AND trade_date BETWEEN '2024-12-01' AND '2024-12-31'
ORDER BY trade_date;

-- 3. 按原始表范围查看下载规模；范围边界不代表中间连续。
SELECT * FROM "期货_数据覆盖" ORDER BY 数据接口,合约或交易所;

-- 4. 关联缺口分类计数；同一日期可以缺多个接口。
SELECT 数据接口,原因,count(*) AS 缺口行数
FROM "期货_数据缺口" GROUP BY 数据接口,原因;

-- 5. 因子中文逻辑与实验 ID。
SELECT id AS 因子ID, json_extract(payload,'$.name_zh') AS 因子名称,
       json_extract(payload,'$.expression') AS 表达式,
       json_extract(payload,'$.logic_zh') AS 中文逻辑,
       json_extract(payload,'$.status') AS 状态,
       json_extract(payload,'$.experiment') AS 实验ID
FROM objects WHERE kind='factors' ORDER BY created DESC;

-- 6. 实验关联因子及快照；每个实验的每个分段一行。
SELECT e.id AS 实验ID, json_extract(f.payload,'$.name_zh') AS 因子名称,
       json_extract(e.payload,'$.snapshot') AS 快照ID,
       json_extract(s.payload,'$.start') AS 快照开始,
       json_extract(s.payload,'$.end') AS 快照结束,
       seg.key AS 分段,
       json_extract(seg.value,'$.metrics.total_return') AS 净收益比例,
       json_extract(seg.value,'$.metrics.sharpe') AS 夏普,
       json_extract(seg.value,'$.metrics.max_drawdown') AS 最大回撤原值,
       json_extract(seg.value,'$.daily') AS 逐日账本相对路径
FROM objects e
LEFT JOIN objects f ON f.kind='factors' AND f.id=json_extract(e.payload,'$.factor_id')
LEFT JOIN objects s ON s.kind='snapshots' AND s.id=json_extract(e.payload,'$.snapshot')
JOIN json_each(e.payload,'$.segments') seg
WHERE e.kind='experiments' ORDER BY e.created DESC,seg.key;

-- 7. 最近一条同步任务的完整 SQL 事件链；没有同步任务则返回空集。
SELECT e.seq,t.id AS 任务ID,t.status,e.time,e.event,e.payload
FROM tasks t JOIN events e ON e.task=t.id
WHERE t.id=(SELECT id FROM tasks WHERE kind='sync' ORDER BY created DESC LIMIT 1)
ORDER BY e.seq;

-- 8. 一条行情追溯来源：迁移导入行可能没有对应 tasks 记录。
SELECT b.ts_code,b.trade_date,b._updated_at,b._source_task,
       t.kind AS 任务类型,t.status AS 任务状态
FROM daily_bars b LEFT JOIN tasks t ON t.id=b._source_task
WHERE b.ts_code='CU2502.SHF' AND b.trade_date='2024-12-31';

-- 9. 迁移来源与备份位置。
SELECT name,completed_at,
       json_extract(report_json,'$.id') AS 迁移运行ID,
       json_extract(report_json,'$.backup') AS 备份位置
FROM market_migrations;

-- 10. 原始字段顺序和 pandas 类型目录。
SELECT dataset,symbol,row_count,updated_at,schema_json
FROM market_catalog WHERE dataset='fut_daily' AND symbol='CU2502.SHF';

-- 11. 可补充下载缺口及其处理状态。
SELECT * FROM "期货_下载缺口记录" ORDER BY 状态,缺失日期,合约代码;
