-- DBeaver 连接 runtime/research.sqlite，以下全部为只读查询。
-- 1. 每类原始数据的覆盖统计
SELECT * FROM "期货_数据覆盖" ORDER BY 数据接口, 合约或交易所;

-- 2. 查看指定月份合约（真实成交价格），日期和合约可自行修改
SELECT * FROM "沪铜_月份合约行情"
WHERE 合约代码 = 'CU2401.SHF' AND 交易日 BETWEEN '2024-01-01' AND '2024-01-15'
ORDER BY 交易日;

-- 3. 查看主连与月份合约的映射
SELECT * FROM "沪铜_主力映射"
WHERE 交易日 BETWEEN '2024-12-01' AND '2024-12-31' ORDER BY 交易日;

-- 4. 主连的原始拼接行情【未复权】，不直接用换月跳空计算回测收益
SELECT * FROM "沪铜_主连未复权行情"
WHERE 交易日 BETWEEN '2024-12-01' AND '2024-12-31' ORDER BY 交易日;

-- 5. 关联缺口；此表反映原始分段，不等于冻结研究快照存在缺口
SELECT 数据接口, COUNT(*) AS 关联缺口数 FROM "期货_数据缺口" GROUP BY 数据接口;
SELECT * FROM "期货_数据缺口" ORDER BY 交易日, 合约代码 LIMIT 100;

-- 6. 查看合约到期信息
SELECT * FROM "期货_合约信息" WHERE 合约代码 IN ('CU2412.SHF', 'CU2501.SHF');
