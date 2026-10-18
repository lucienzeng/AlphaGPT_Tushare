# ETF专题

> 来源：Tushare 数据接口文档 · <https://tushare.pro/document/2?doc_id=384>  
> 整理时间：2026-10-12  
> 收录该分类下全部 15 个接口文档。

## 目录

- ETF基本信息
- ETF跟踪指数
- ETF实时分钟
- ETF实时分钟-日累计
- ETF历史分钟
- ETF实时日线
- ETF日线行情
- ETF当日集合竞价
- ETF复权因子
- ETF每日涨跌停价格
- ETF份额规模
- 每日篮子组合(沪市PCF）
- 每日篮子组合(深市PCF）
- ETF实时参考
- 指数公司公告

---

## ETF基本信息

接口：etf_basic
描述：获取国内ETF基础信息，包括了QDII。数据来源与沪深交易所公开披露信息。
限量：单次请求最大放回5000条数据（当前ETF总数未超过2000）
权限：用户积8000积分可调取，具体请参阅[积分获取办法](https://tushare.pro/document/1?doc_id=13)

**输入参数**

| 名称 | 类型 | 必选 | 描述 |
| --- | --- | --- | --- |
| ts_code | str | N | ETF代码（带.SZ/.SH后缀的6位数字，如：159526.SZ） |
| index_code | str | N | 跟踪指数代码 |
| list_date | str | N | 上市日期（格式：YYYYMMDD） |
| list_status | str | N | 上市状态（L上市 D退市 P待上市） |
| exchange | str | N | 交易所（SH上交所 SZ深交所） |
| mgr | str | N | 管理人（简称，e.g.华夏基金) |

**输出参数**

| 名称 | 类型 | 默认显示 | 描述 |
| --- | --- | --- | --- |
| ts_code | str | Y | 基金交易代码 |
| csname | str | Y | ETF中文简称 |
| extname | str | Y | ETF扩位简称(对应交易所简称) |
| cname | str | Y | 基金中文全称 |
| index_code | str | Y | ETF基准指数代码 |
| index_name | str | Y | ETF基准指数中文全称 |
| setup_date | str | Y | 设立日期（格式：YYYYMMDD） |
| list_date | str | Y | 上市日期（格式：YYYYMMDD） |
| list_status | str | Y | 存续状态（L上市 D退市 P待上市） |
| exchange | str | Y | 交易所（上交所SH 深交所SZ） |
| mgr_name | str | Y | 基金管理人简称 |
| custod_name | str | Y | 基金托管人名称 |
| mgt_fee | float | Y | 基金管理人收取的费用 |
| etf_type | str | Y | 基金投资通道类型（境内、QDII） |

**接口示例**

```
#获取当前所有上市的ETF列表
df = pro.etf_basic(list_status='L', fields='ts_code,extname,index_code,index_name,exchange,mgr_name')

#获取“嘉实基金”所有上市的ETF列表
df = pro.etf_basic(mgr='嘉实基金'， list_status='L', fields='ts_code,extname,index_code,index_name,exchange,etf_type')

#获取“嘉实基金”在深交所上市的所有ETF列表
df = pro.etf_basic(mgr='嘉实基金'， list_status='L', exchange='SZ', fields='ts_code,extname,index_code,index_name,exchange,etf_type')

#获取以沪深300指数为跟踪指数的所有上市的ETF列表
df = pro.etf_basic(index_code='000300.SH', fields='ts_code,extname,index_code,index_name,exchange,mgr_name')
```

**数据示例**

```
      ts_code       extname    index_code    index_name exchange   mgr_name
0   159238.SZ      300ETF增强  000300.SH    沪深300指数       SZ   景顺长城基金
1   159300.SZ        300ETF  000300.SH    沪深300指数       SZ     富国基金
2   159330.SZ    沪深300ETF基金  000300.SH    沪深300指数       SZ   西藏东财基金
3   159393.SZ    沪深300指数ETF  000300.SH    沪深300指数       SZ     万家基金
4   159673.SZ    沪深300ETF鹏华  000300.SH    沪深300指数       SZ     鹏华基金
5   159919.SZ      沪深300ETF  000300.SH    沪深300指数       SZ     嘉实基金
6   159925.SZ    沪深300ETF南方  000300.SH    沪深300指数       SZ     南方基金
7   159927.SZ     鹏华沪深300指数  000300.SH    沪深300指数       SZ     鹏华基金
8   510300.SH      沪深300ETF  000300.SH    沪深300指数       SH   华泰柏瑞基金
9   510310.SH   沪深300ETF易方达  000300.SH    沪深300指数       SH    易方达基金
10  510320.SH    沪深300ETF中金  000300.SH    沪深300指数       SH     中金基金
11  510330.SH    沪深300ETF华夏  000300.SH    沪深300指数       SH     华夏基金
12  510350.SH    沪深300ETF工银  000300.SH    沪深300指数       SH   工银瑞信基金
13  510360.SH    沪深300ETF基金  000300.SH    沪深300指数       SH     广发基金
14  510370.SH      300指数ETF  000300.SH    沪深300指数       SH     兴业基金
15  510380.SH      国寿300ETF  000300.SH    沪深300指数       SH   国寿安保基金
16  510390.SH    沪深300ETF平安  000300.SH    沪深300指数       SH     平安基金
17  515130.SH    沪深300ETF博时  000300.SH    沪深300指数       SH     博时基金
18  515310.SH    沪深300指数ETF  000300.SH    沪深300指数       SH    汇添富基金
19  515330.SH    沪深300ETF天弘  000300.SH    沪深300指数       SH     天弘基金
20  515350.SH    民生加银300ETF  000300.SH    沪深300指数       SH   民生加银基金
21  515360.SH    方正沪深300ETF  000300.SH    沪深300指数       SH   方正富邦基金
22  515380.SH    沪深300ETF泰康  000300.SH    沪深300指数       SH     泰康基金
23  515390.SH  沪深300ETF指数基金  000300.SH    沪深300指数       SH     华安基金
24  515660.SH   沪深300ETF国联安  000300.SH    沪深300指数       SH    国联安基金
25  515930.SH    永赢沪深300ETF  000300.SH    沪深300指数       SH     永赢基金
26  561000.SH  沪深300ETF增强基金  000300.SH    沪深300指数       SH     华安基金
27  561300.SH      300增强ETF  000300.SH    沪深300指数       SH     国泰基金
28  561930.SH    沪深300ETF招商  000300.SH    沪深300指数       SH     招商基金
29  561990.SH    沪深300增强ETF  000300.SH    沪深300指数       SH     招商基金
30  563520.SH    沪深300ETF永赢  000300.SH    沪深300指数       SH     永赢基金
```

---

## ETF跟踪指数

接口：etf_index
描述：获取ETF基准指数列表信息
限量：单次请求最大返回5000行数据（当前未超过2000个）
权限：用户积累8000积分可调取，具体请参阅[积分获取办法](https://tushare.pro/document/1?doc_id=13)

**输入参数**

| 名称 | 类型 | 必选 | 描述 |
| --- | --- | --- | --- |
| ts_code | str | N | 指数代码 |
| pub_date | str | N | 发布日期（格式：YYYYMMDD） |
| base_date | str | N | 指数基期（格式：YYYYMMDD） |

**输出参数**

| 名称 | 类型 | 默认显示 | 描述 |
| --- | --- | --- | --- |
| ts_code | str | Y | 指数代码 |
| indx_name | str | Y | 指数全称 |
| indx_csname | str | Y | 指数简称 |
| pub_party_name | str | Y | 指数发布机构 |
| pub_date | str | Y | 指数发布日期 |
| base_date | str | Y | 指数基日 |
| bp | float | Y | 指数基点(点) |
| adj_circle | str | Y | 指数成份证券调整周期 |

**接口示例**

```
#获取当前ETF跟踪的基准指数列表
df = pro.etf_index(fields='ts_code,indx_name,pub_date,bp')
```

**数据示例**

```
          ts_code        indx_name         pub_date           bp
0        000068.SH         上证自然资源指数  20100528  1000.000000
1        000001.SH           上证综合指数  19910715   100.000000
2        000989.SH       中证全指可选消费指数  20110802  1000.000000
3       000990.CSI       中证全指主要消费指数  20110802  1000.000000
4        000043.SH         上证超级大盘指数  20090423  1000.000000
...            ...              ...       ...          ...
1458    932368.CSI     中证800自由现金流指数  20241211  1000.000000
1460     000680.SH        上证科创板综合指数  20250120  1000.000000
1461     000681.SH      上证科创板综合价格指数  20250120  1000.000000
```

---

## ETF实时分钟

接口：rt_etf_min
描述：获取ETF实时分钟数据，包括1~60min
限量：单次最大1000行数据，可以通过ETF代码提取数据，支持逗号分隔的多个代码同时提取
权限：正式权限请参阅 [权限说明](https://tushare.pro/document/1?doc_id=290)

注：支持股票当日开盘以来的所有ETF历史分钟数据提取，接口名：rt_etf_min_daily（仅支持一个个代码提取，不同同时提取多个），可以[在线开通](https://tushare.pro/weborder/#/permission)权限。

**输入参数**

| 名称 | 类型 | 必选 | 描述 |
| --- | --- | --- | --- |
| freq | str | Y | 1MIN,5MIN,15MIN,30MIN,60MIN （大写） |
| ts_code | str | Y | 支持单个和多个：589960.SH 或者 589960.SH,159100.SZ |

**freq参数说明**

| freq | 说明 |
| --- | --- |
| 1MIN | 1分钟 |
| 5MIN | 5分钟 |
| 15MIN | 15分钟 |
| 30MIN | 30分钟 |
| 60MIN | 60分钟 |

**输出参数**

| 名称 | 类型 | 默认显示 | 描述 |
| --- | --- | --- | --- |
| ts_code | str | Y | 股票代码 |
| time | None | Y | 交易时间 |
| open | float | Y | 开盘价 |
| close | float | Y | 收盘价 |
| high | float | Y | 最高价 |
| low | float | Y | 最低价 |
| vol | float | Y | 成交量(股） |
| amount | float | Y | 成交额（元） |

**接口用法**

```
pro = ts.pro_api()

#获取科创新能源ETF易方达589960.SH的实时分钟数据
df = pro.rt_etf_min(ts_code='589960.SH', freq='1MIN')
```

---

## ETF实时分钟-日累计

接口：rt_etf_min_daily
描述：获取ETF实时分钟数据日累计，包括1~60min
限量：单次最大1000行数据，支持股票当日开盘以来的所有ETF历史分钟数据提取（仅支持一个个代码提取，不同同时提取多个）
权限：正式权限请参阅 [权限说明](https://tushare.pro/document/1?doc_id=290)

**输入参数**

| 名称 | 类型 | 必选 | 描述 |
| --- | --- | --- | --- |
| freq | str | Y | 1MIN,5MIN,15MIN,30MIN,60MIN （大写） |
| ts_code | str | Y | 只支持单个 |

**freq参数说明**

| freq | 说明 |
| --- | --- |
| 1MIN | 1分钟 |
| 5MIN | 5分钟 |
| 15MIN | 15分钟 |
| 30MIN | 30分钟 |
| 60MIN | 60分钟 |

**输出参数**

| 名称 | 类型 | 默认显示 | 描述 |
| --- | --- | --- | --- |
| ts_code | str | Y | 股票代码 |
| time | None | Y | 交易时间 |
| open | float | Y | 开盘价 |
| close | float | Y | 收盘价 |
| high | float | Y | 最高价 |
| low | float | Y | 最低价 |
| vol | float | Y | 成交量(股） |
| amount | float | Y | 成交额（元） |

**代码示例**

```
# 导入sdk包
import tushare as ts

# 配置凭据，如果已全局配置了，可以忽略。
ts.set_token('<--your-token-->')

# 获取接口实例
pro = ts.pro_api()
# 获取科创芯片设计ETF（588780.SH）当日1分钟实时行情
df = pro.rt_etf_min_daily(ts_code='588780.SH',freq='1MIN')
```

**数据结果**

```
         code  freq                 time   open  close   high    low         vol      amount
0   588780.SH  1MIN  2026-06-10 09:30:00  1.024  1.024  1.024  1.024    729200.0    746701.0
1   588780.SH  1MIN  2026-06-10 09:31:00  1.024  1.038  1.038  1.024   3068800.0   3169337.0
2   588780.SH  1MIN  2026-06-10 09:32:00  1.038  1.052  1.052  1.038   4226200.0   4415521.0
3   588780.SH  1MIN  2026-06-10 09:33:00  1.053  1.048  1.055  1.048   3050700.0   3209216.0
4   588780.SH  1MIN  2026-06-10 09:34:00  1.048  1.047  1.050  1.046   6535400.0   6853982.0
5   588780.SH  1MIN  2026-06-10 09:35:00  1.047  1.056  1.057  1.047   4770400.0   5010528.0
6   588780.SH  1MIN  2026-06-10 09:36:00  1.057  1.061  1.062  1.056   4914000.0   5197668.0
7   588780.SH  1MIN  2026-06-10 09:37:00  1.060  1.059  1.061  1.058   2550800.0   2701928.0
8   588780.SH  1MIN  2026-06-10 09:38:00  1.060  1.062  1.062  1.058   2812800.0   2980502.0
9   588780.SH  1MIN  2026-06-10 09:39:00  1.063  1.062  1.064  1.060  13340700.0  14165413.0
10  588780.SH  1MIN  2026-06-10 09:40:00  1.060  1.060  1.061  1.059   5964500.0   6321852.0
```

---

## ETF历史分钟

接口：etf_mins
描述：获取ETF分钟数据，支持1min/5min/15min/30min/60min行情，提供Python SDK和 http Restful API两种方式
限量：单次最大8000行数据，可以通过股票代码和时间循环获取，本接口可以提供超过10年ETF历史分钟数据
权限：正式权限请参阅 [权限说明](https://tushare.pro/document/1?doc_id=290)

**输入参数**

| 名称 | 类型 | 必选 | 描述 |
| --- | --- | --- | --- |
| ts_code | str | Y | ETF代码，e.g. 159001.SZ |
| freq | str | Y | 分钟频度（1min/5min/15min/30min/60min） |
| start_date | datetime | N | 开始日期 格式：2025-06-01 09:00:00 |
| end_date | datetime | N | 结束时间 格式：2025-06-20 19:00:00 |

**freq参数说明**

| freq | 说明 |
| --- | --- |
| 1min | 1分钟 |
| 5min | 5分钟 |
| 15min | 15分钟 |
| 30min | 30分钟 |
| 60min | 60分钟 |

**输出参数**

| 名称 | 类型 | 默认显示 | 描述 |
| --- | --- | --- | --- |
| ts_code | str | Y | ETF代码 |
| trade_time | str | Y | 交易时间 |
| open | float | Y | 开盘价 |
| close | float | Y | 收盘价 |
| high | float | Y | 最高价 |
| low | float | Y | 最低价 |
| vol | int | Y | 成交量（股） |
| amount | float | Y | 成交金额（元） |

**接口用法**

```
pro = ts.pro_api()

#获取沪深300ETF华夏510330.SH的历史分钟数据
df = pro.etf_mins(ts_code='510330.SH', freq='1min', start_date='2025-06-20 09:00:00', end_date='2025-06-20 19:00:00')
```

**数据样例**

```
       ts_code           trade_time  close   open   high    low        vol      amount
0    510330.SH  2025-06-20 15:00:00  3.991  3.991  3.992  3.990   800600.0   3194805.0
1    510330.SH  2025-06-20 14:59:00  3.991  3.990  3.991  3.989   182500.0    728177.0
2    510330.SH  2025-06-20 14:58:00  3.990  3.992  3.992  3.990   113700.0    453763.0
3    510330.SH  2025-06-20 14:57:00  3.992  3.992  3.992  3.991    17400.0     69460.0
4    510330.SH  2025-06-20 14:56:00  3.992  3.992  3.992  3.991   447500.0   1786373.0
..         ...                  ...    ...    ...    ...    ...        ...         ...
236  510330.SH  2025-06-20 09:34:00  3.994  3.994  3.995  3.994  2528100.0  10097818.0
237  510330.SH  2025-06-20 09:33:00  3.994  3.991  3.994  3.991   143300.0    572084.0
238  510330.SH  2025-06-20 09:32:00  3.992  3.990  3.993  3.990  1118500.0   4463264.0
239  510330.SH  2025-06-20 09:31:00  3.988  3.984  3.992  3.984  1176100.0   4691600.0
240  510330.SH  2025-06-20 09:30:00  3.983  3.983  3.983  3.983    20700.0     82448.0
```

---

## ETF实时日线

接口：rt_etf_k
描述：获取ETF实时日k线行情，支持按ETF代码或代码通配符一次性提取全部ETF实时日k线行情
积分：本接口是单独开权限的数据，单独申请权限请参考[权限列表](https://tushare.pro/document/1?doc_id=290)

**输入参数**

| 名称 | 类型 | 必选 | 描述 |
| --- | --- | --- | --- |
| ts_code | str | Y | 支持通配符方式，e.g. 5*.SH、15*.SZ、159101.SZ |
| topic | str | Y | 分类参数，取上海ETF时，需要输入'HQ_FND_TICK'，参考下面例子 |

注：ts_code代码一定要带.SH/.SZ/.BJ后缀

**输出参数**

| 名称 | 类型 | 默认显示 | 描述 |
| --- | --- | --- | --- |
| ts_code | str | Y | ETF代码 |
| name | None | Y | ETF名称 |
| pre_close | float | Y | 昨收价（元） |
| high | float | Y | 最高价（元） |
| open | float | Y | 开盘价（元） |
| low | float | Y | 最低价（元） |
| close | float | Y | 收盘价（最新价） |
| vol | int | Y | 成交量（股） |
| amount | int | Y | 成交金额（元） |
| num | int | Y | 开盘以来成交笔数 |
| ask_volume1 | int | N | 委托卖盘（股） |
| bid_volume1 | int | N | 委托买盘（股） |
| trade_time | str | N | 交易时间 |

**接口示例**

```
#获取今日所有深市ETF实时日线和成交笔数
df = pro.rt_etf_k(ts_code='1*.SZ')

#获取今日沪市所有ETF实时日线和成交笔数
df = pro.rt_etf_k(ts_code='5*.SH', topic='HQ_FND_TICK')
```

**数据示例**

```
       ts_code      name      pre_close     high     open     low    close        vol     amount    num
0    520860.SH      港股通科      1.024    1.054    1.048   1.041    1.048   15071600   15780985    307
1    515320.SH    电子50        1.173    1.211    1.184   1.184    1.206    1830600    2191339     98
2    511600.SH    货币ETF     100.008  100.003  100.002  99.999  100.000      12022    1202204     28
3    501075.SH      科创主题      2.350    2.400    2.357   2.357    2.400       4200      10040     11
4    589990.SH      科创板综      1.282    1.311    1.280   1.280    1.305    4178600    5413728    147
..         ...       ...        ...      ...      ...     ...      ...        ...        ...    ...
933  516590.SH      电动汽车      1.244    1.277    1.252   1.252    1.270    1380800    1748398     79
934  502048.SH  50LOF         1.224    1.238    1.235   1.214    1.218       3200       3908      5
935  515850.SH      证券龙头      1.519    1.538    1.523   1.520    1.523   11460000   17484157    688
936  515790.SH    光伏ETF       0.912    0.929    0.919   0.910    0.923  411566128  379094370  14939
937  516190.SH    文娱ETF       1.137    1.154    1.151   1.146    1.151    1031700    1186303     87
```

---

## ETF日线行情

接口：fund_daily
描述：获取ETF行情每日收盘后成交数据，历史超过10年
限量：单次最大5000行记录，可以根据ETF代码和日期循环获取历史，总量不限制
积分：需要至少5000积分才可以调取，8000积分频次更高，具体请参阅[积分获取办法](https://tushare.pro/document/1?doc_id=13)

**输入参数**

| 名称 | 类型 | 必选 | 描述 |
| --- | --- | --- | --- |
| ts_code | str | N | 基金代码 |
| trade_date | str | N | 交易日期(YYYYMMDD格式，下同) |
| start_date | str | N | 开始日期 |
| end_date | str | N | 结束日期 |

**输出参数**

| 名称 | 类型 | 默认显示 | 描述 |
| --- | --- | --- | --- |
| ts_code | str | Y | TS代码 |
| trade_date | str | Y | 交易日期 |
| open | float | Y | 开盘价(元) |
| high | float | Y | 最高价(元) |
| low | float | Y | 最低价(元) |
| close | float | Y | 收盘价(元) |
| pre_close | float | Y | 昨收盘价(元) |
| change | float | Y | 涨跌额(元) |
| pct_chg | float | Y | 涨跌幅(%) |
| vol | float | Y | 成交量(手) |
| amount | float | Y | 成交额(千元) |

**接口示例**

```
pro = ts.pro_api()

#获取”沪深300ETF华夏”ETF2025年以来的行情，并通过fields参数指定输出了部分字段
df = pro.fund_daily(ts_code='510330.SH', start_date='20250101', end_date='20250618', fields='trade_date,open,high,low,close,vol,amount')
```

**数据示例**

```
   trade_date   open   high    low  close         vol       amount
0     20250618  4.008  4.024  3.996  4.017   382896.00   153574.446
1     20250617  4.015  4.022  4.000  4.014   440272.04   176617.125
2     20250616  4.000  4.018  3.996  4.015   423526.00   169788.251
3     20250613  4.023  4.028  3.992  4.004  1216787.53   487632.318
4     20250612  4.023  4.039  4.005  4.032   574727.00   231356.321
..         ...    ...    ...    ...    ...         ...          ...
104   20250108  3.971  3.992  3.908  3.963  3200416.00  1267465.456
105   20250107  3.939  3.974  3.929  3.973  2239739.00   885818.954
106   20250106  3.950  3.964  3.917  3.943  1583794.00   624004.760
107   20250103  4.002  4.013  3.944  3.963  2025111.00   805573.289
108   20250102  4.110  4.117  3.973  4.001  1768592.00   714820.885
```

---

## ETF当日集合竞价

### 接口介绍

接口：etf_auction
描述：获取当日ETF的集合竞价成交情况，每天9点25~29分之间可以获取当日的集合竞价成交数据本接口历史数据开始于2025年1月。
限量：单次最大3000条，可根据代码或日期循环提取
积分：本接口是单独开权限的数据，单独申请权限请参考[权限列表](https://tushare.pro/document/1?doc_id=290)。

### 输入参数

| 名称 | 类型 | 必选 | 描述 |
| --- | --- | --- | --- |
| ts_code | str | N | 股票代码 |
| trade_date | str | N | 交易日期（YYYYMMDD格式，下同) |
| start_date | str | N | 开始日期 |
| end_date | str | N | 结束日期 |

### 输出参数

| 名称 | 类型 | 默认显示 | 描述 |
| --- | --- | --- | --- |
| ts_code | str | Y | 股票代码 |
| trade_date | str | Y | 交易日期 |
| vol | int | Y | 成交量 |
| price | float | Y | 成交均价（元） |
| amount | float | Y | 成交金额（元） |
| pre_close | float | Y | 昨收价 |
| turnover_rate | float | Y | 换手率（%） |
| volume_ratio | float | Y | 量比 |
| float_share | float | Y | 流通股本（万股） |

### 代码示例

```
# 导入sdk包
import tushare as ts

# 配置凭据，如果已全局配置了，可以忽略。
ts.set_token('<--your-token-->')

# 获取接口实例
pro = ts.pro_api()

# 拉取接口(etf_auction)数据
#获取180607.SZ的开盘集合竞价成交情况
df=pro.etf_auction(ts_code='180607.SZ')

# 获取2026年9月11日开盘集合竞价成交情况
df=pro.etf_auction(trade_date='20260911',fields='ts_code, trade_date,vol,price,amount,turnover_rate,volume_ratio')
print(df)
```

### 数据结果

```
     ts_code trade_date  vol  price  amount turnover_rate  volume_ratio
0     501001.SH   20260911    0    NaN     0.0          None      0.000000
1     501005.SH   20260911    0    NaN     0.0          None      0.000000
2     501007.SH   20260911    0    NaN     0.0          None      0.000000
3     501008.SH   20260911    0    NaN     0.0          None      0.000000
4     501009.SH   20260911    0    NaN     0.0          None      0.000000
...         ...        ...  ...    ...     ...           ...           ...
1711  180607.SZ   20260911  700  5.050  3535.0          None      0.251875
1712  180701.SZ   20260911  300  3.836  1150.8          None      0.039973
1713  180801.SZ   20260911    0    NaN     0.0          None      0.000000
1714  180901.SZ   20260911    0    NaN     0.0          None      0.000000
1715  181001.SZ   20260911    0    NaN     0.0          None      0.000000
```

---

## ETF复权因子

接口：fund_adj
描述：获取基金复权因子，用于计算基金复权行情
限量：单次最大提取2000行记录，可循环提取，数据总量不限制
积分：用户积2000积分可调取，超过5000积分以上频次相对较高。具体请参阅[积分获取办法](https://tushare.pro/document/1?doc_id=13)

**输入参数**

| 名称 | 类型 | 必选 | 描述 |
| --- | --- | --- | --- |
| ts_code | str | N | TS基金代码（支持多只基金输入） |
| trade_date | str | N | 交易日期（格式：yyyymmdd，下同） |
| start_date | str | N | 开始日期 |
| end_date | str | N | 结束日期 |
| offset | str | N | 开始行数 |
| limit | str | N | 最大行数 |

**输出参数**

| 名称 | 类型 | 默认显示 | 描述 |
| --- | --- | --- | --- |
| ts_code | str | Y | ts基金代码 |
| trade_date | str | Y | 交易日期 |
| adj_factor | float | Y | 复权因子 |

**接口使用**

```
pro = ts.pro_api()

df = pro.fund_adj(ts_code='513100.SH', start_date='20190101', end_date='20190926')
```

**数据示例**

```
     ts_code    trade_date  adj_factor
0    513100.SH   20190926         1.0
1    513100.SH   20190925         1.0
2    513100.SH   20190924         1.0
3    513100.SH   20190923         1.0
4    513100.SH   20190920         1.0
5    513100.SH   20190919         1.0
6    513100.SH   20190918         1.0
7    513100.SH   20190917         1.0
8    513100.SH   20190916         1.0
9    513100.SH   20190912         1.0
10   513100.SH   20190911         1.0
11   513100.SH   20190910         1.0
12   513100.SH   20190909         1.0
13   513100.SH   20190906         1.0
14   513100.SH   20190905         1.0
15   513100.SH   20190904         1.0
16   513100.SH   20190903         1.0
17   513100.SH   20190902         1.0
18   513100.SH   20190830         1.0
19   513100.SH   20190829         1.0
20   513100.SH   20190828         1.0
```

---

## ETF每日涨跌停价格

### 接口介绍

接口：etf_limit
描述：获取ETF每日涨跌停价格，包括涨停价格，跌停价格等，每个交易日8点40左右更新当日股票涨跌停价格。
限量：单次最大3000条，可根据代码或日期循环提取
积分：需要2000积分可以调取，具体请参阅[积分获取办法](https://tushare.pro/document/1?doc_id=13)

### 输入参数

| 名称 | 类型 | 必选 | 描述 |
| --- | --- | --- | --- |
| ts_code | str | N | 股票代码 |
| trade_date | str | N | 交易日期 |
| start_date | str | N | 开始日期 |
| end_date | str | N | 结束日期 |

### 输出参数

| 名称 | 类型 | 默认显示 | 描述 |
| --- | --- | --- | --- |
| trade_date | str | Y | 交易日期 |
| ts_code | str | Y | 合约代码 |
| pre_close | float | N | 昨日收盘价 |
| up_limit | float | Y | 涨停价 |
| down_limit | float | Y | 跌停价 |
| asset_type | str | N | 类型 ETF |
| exchange | str | N | 交易所：SSE/SZSE |

### 代码示例

```
# 导入sdk包
import tushare as ts

# 配置凭据，如果已全局配置了，可以忽略。
ts.set_token('<--your-token-->')

# 获取接口实例
pro = ts.pro_api()

# 拉取接口(etf_limit)数据

# 示例：获取159001.SZ涨跌停价格
df = pro.etf_limit(ts_code='159001.SZ')

# 示例：获取2026年6月25日ETF涨跌停价格
df = pro.etf_limit(trade_date='20260625')
print(df)
```

### 数据结果

```
     trade_date    ts_code asset_type exchange  up_limit  down_limit
0      20260625  159001.SZ        ETF     SZSE   110.001      90.001
1      20260625  159003.SZ        ETF     SZSE   110.000      90.000
2      20260625  159005.SZ        ETF     SZSE   109.999      89.999
3      20260625  159007.SZ        ETF     SZSE     0.854       0.698
4      20260625  159008.SZ        ETF     SZSE     1.141       0.933
...         ...        ...        ...      ...       ...         ...
2053   20260625  589900.SH        ETF      SSE     2.260       1.506
2054   20260625  589950.SH        ETF      SSE     1.870       1.246
2055   20260625  589960.SH        ETF      SSE     1.306       0.870
2056   20260625  589980.SH        ETF      SSE     2.573       1.715
2057   20260625  589990.SH        ETF      SSE     2.300       1.534
```

---

## ETF份额规模

### 接口介绍

接口：etf_share_size
描述：获取沪深ETF每日份额和规模数据，能体现规模份额的变化，掌握ETF资金动向，同时提供每日净值和收盘价；数据指标是分批入库，交易所于次日早8点30左右更新上一交易日的数据；另外，涉及海外的ETF数据更新会晚一些属于正常情况。
限量：单次最大5000条，可根据代码或日期循环提取
积分：需要8000积分可以调取，具体请参阅[积分获取办法](https://tushare.pro/document/1?doc_id=13)

### 输入参数

| 名称 | 类型 | 必选 | 描述 |
| --- | --- | --- | --- |
| ts_code | str | N | 基金代码 （可从ETF基础信息接口提取） |
| trade_date | str | N | 交易日期（YYYYMMDD格式，下同） |
| start_date | str | N | 开始日期 |
| end_date | str | N | 结束日期 |
| exchange | str | N | 交易所（SSE上交所 SZSE深交所） |

### 输出参数

| 名称 | 类型 | 默认显示 | 描述 |
| --- | --- | --- | --- |
| trade_date | str | Y | 交易日期 |
| ts_code | str | Y | ETF代码 |
| etf_name | str | Y | 基金名称 |
| total_share | float | Y | 总份额（万份） |
| total_size | float | Y | 总规模（万元） |
| nav | float | N | 基金份额净值(元) |
| close | float | N | 收盘价（元） |
| exchange | str | Y | 交易所（SSE上交所 SZSE深交所 BSE北交所） |

### 代码示例

```
#获取”沪深300ETF华夏”ETF2025年以来每个交易日的份额和规模情况
df = pro.etf_share_size(ts_code='510330.SH', start_date='20250101', end_date='20251224')

#获取2025年12月24日上交所的所有ETF份额和规模情况
df = pro.etf_share_size(trade_date='20251224', exchange='SSE')
```

### 数据结果

```
    trade_date    ts_code       etf_name  total_share    total_size exchange
0     20251224  510330.SH  沪深300ETF华夏   4741854.98  2.287898e+07      SSE
1     20251222  510330.SH  沪深300ETF华夏   4746894.98  2.279127e+07      SSE
2     20251219  510330.SH  沪深300ETF华夏   4756974.98  2.262512e+07      SSE
3     20251218  510330.SH  沪深300ETF华夏   4757514.98  2.253778e+07      SSE
4     20251217  510330.SH  沪深300ETF华夏   4756884.98  2.266418e+07      SSE
..         ...        ...         ...          ...           ...      ...
232   20250108  510330.SH  沪深300ETF华夏   4032384.98  1.599808e+07      SSE
233   20250107  510330.SH  沪深300ETF华夏   4009164.98  1.592962e+07      SSE
234   20250106  510330.SH  沪深300ETF华夏   3999084.98  1.577239e+07      SSE
235   20250103  510330.SH  沪深300ETF华夏   3994674.98  1.578176e+07      SSE
236   20250102  510330.SH  沪深300ETF华夏   3986754.98  1.593905e+07      SSE
```

---

## 每日篮子组合(沪市PCF）

### 接口介绍

接口：etf_sh_cons
描述：获取上交所场内所有ETF每日盘前披露的的一篮子组合信息,包括成分股票数量、申赎现金折溢价比例等数据
限量：单次最大3000条，可根据代码或日期循环提取
积分：需要8000积分可以调取，具体请参阅[积分获取办法](https://tushare.pro/document/1?doc_id=13)

### 输入参数

| 名称 | 类型 | 必选 | 描述 |
| --- | --- | --- | --- |
| ts_code | str | N | 板块代码 |
| trade_date | str | N | 交易日期(YYYYMMDD) |
| con_code | str | N | 成分股票代码 |
| start_date | str | N | 开始日期(YYYYMMDD) |
| end_date | str | N | 结束日期(YYYYMMDD) |

### 输出参数

| 名称 | 类型 | 默认显示 | 描述 |
| --- | --- | --- | --- |
| trade_date | str | Y | 交易日期 |
| ts_code | str | Y | ETF代码 |
| con_code | str | Y | 成分代码 |
| con_name | str | Y | 成分名称 |
| qty | int | Y | 股票数量(股) |
| sub_flag | str | Y | 现金替代标志：允许/必须 |
| cpr | float | Y | 申购现金替代溢价比率（%） |
| rdr | float | Y | 赎回现金替代折价比率（%） |
| sca | float | Y | 替代金额(单位：人民币元) |
| exchange | str | Y | 交易所代码HK港交所 SH上交所 SZ深交所 OTH其他 |

### 代码示例

```
# 获取接口实例
pro = ts.pro_api()

# 获取517030易方达中证沪港深300ETF在2026年6月15日的持仓组合信息
df = pro.etf_sh_cons(trade_date='20260615', ts_code='517030.SH')
print(df)
```

### 数据结果

```
    trade_date    ts_code   con_code con_name   qty sub_flag cpr rdr        sca exchange
0     20260615  517030.SH  000001.SZ     平安银行  1100       允许  15  60  12364.000       SZ
1     20260615  517030.SH   00001.HK       长和     0       必须   -   -      0.000       HK
2     20260615  517030.SH   00002.HK     中电控股     0       必须   -   -      0.000       HK
3     20260615  517030.SH   00003.HK   香港中华煤气  1000       允许  30   0   5928.350       HK
4     20260615  517030.SH   00005.HK     汇丰控股   800       允许  30   0  99304.260       HK
..         ...        ...        ...      ...   ...      ...  ..  ..        ...      ...
295   20260615  517030.SH  688256.SH      寒武纪     0       必须   -   -      0.000       SH
296   20260615  517030.SH  688271.SH     联影医疗     0       必须   -   -      0.000       SH
297   20260615  517030.SH  688506.SH     百利天恒     0       必须   -   -      0.000       SH
298   20260615  517030.SH  688521.SH     芯原股份     0       必须   -   -      0.000       SH
299   20260615  517030.SH  688981.SH     中芯国际   200       允许  73   0          -       SH
```

---

## 每日篮子组合(深市PCF）

### 接口介绍

接口：etf_sz_cons
描述：获取深交所场内所有ETF每日盘前披露的一篮子组合信息,包括成分股票数量、申赎现金折溢价比例等数据
限量：单次最大3000条，可根据代码或日期循环提取
积分：需要8000积分可以调取，具体请参阅[积分获取办法](https://tushare.pro/document/1?doc_id=13)

### 输入参数

| 名称 | 类型 | 必选 | 描述 |
| --- | --- | --- | --- |
| ts_code | str | N | 板块代码 |
| trade_date | str | N | 交易日期(YYYYMMDD) |
| con_code | str | N | 成分股票代码 |
| start_date | str | N | 开始日期(YYYYMMDD) |
| end_date | str | N | 结束日期(YYYYMMDD) |

### 输出参数

| 名称 | 类型 | 默认显示 | 描述 |
| --- | --- | --- | --- |
| trade_date | str | Y | 交易日期 |
| ts_code | str | Y | ETF代码 |
| con_code | str | Y | 成分代码 |
| con_name | str | Y | 成分名称 |
| qty | int | Y | 股票数量(股) |
| sub_flag | str | Y | 现金替代标志 |
| cpr | float | Y | 申购现金替代保证金率（%） |
| rdr | float | Y | 赎回现金替代保证金率（%） |
| sub_cc | float | Y | 申购替代金额(单位：人民币元) |
| red_cc | float | Y | 赎回替代金额(单位：人民币元) |
| exchange | str | Y | 交易所代码HK港交所 SH上交所 SZ深交所 OTH其他 |

### 代码示例

```
# 获取接口实例
pro = ts.pro_api()

# 拉取159051.SZ易方达中证全指医疗器械ETF在2026年6月25日的持仓组合数据
df = pro.etf_sz_cons(ts_code='159051.SZ', trade_date='20260625')
print(df)
```

### 数据结果

```
  trade_date    ts_code   con_code con_name   qty sub_flag    cpr   rdr       sub_cc       red_cc exchange
0   20260625  159051.SZ  159900.SZ     申赎现金     0       必须   0.00  0.00  512407.5000  141173.9000       SZ
1   20260625  159051.SZ  000710.SZ     贝瑞基因   400       允许  34.00  0.00       0.0000       0.0000       SZ
2   20260625  159051.SZ  002022.SZ     科华生物   800       允许  34.00  0.00       0.0000       0.0000       SZ
3   20260625  159051.SZ  002030.SZ     达安基因  1500       允许  34.00  0.00       0.0000       0.0000       SZ
4   20260625  159051.SZ  002223.SZ     鱼跃医疗   900       允许  34.00  0.00       0.0000       0.0000       SZ
5   20260625  159051.SZ  002382.SZ     蓝帆医疗  1200       允许  34.00  0.00       0.0000       0.0000       SZ
6   20260625  159051.SZ  002432.SZ     九安医疗   500       允许  34.00  0.00       0.0000       0.0000       SZ
7   20260625  159051.SZ  002551.SZ     尚荣医疗   900       允许  34.00  0.00       0.0000       0.0000       SZ
8   20260625  159051.SZ  002901.SZ     大博医疗   100       允许  34.00  0.00       0.0000       0.0000       SZ
9   20260625  159051.SZ  002950.SZ     奥美医疗   400       允许  34.00  0.00       0.0000       0.0000       SZ
```

---

## ETF实时参考

### 接口介绍

接口：rt_etf_sz_iopv
描述：ETF实时净值和申购赎回数据参考，目前只提供深市
限量：单次最大5000条，完全覆盖当前总量
权限：本接口为单独开权限的接口，跟积分多个无关。正式权限请参阅 [权限说明](https://tushare.pro/document/1?doc_id=290)

### 输入参数

| 名称 | 类型 | 必选 | 描述 |
| --- | --- | --- | --- |
| ts_code | str | N | ETF代码（默认为空，即一次全市场。支持单个和多个ETF过滤提取） |

### 输出参数

| 名称 | 类型 | 默认显示 | 描述 |
| --- | --- | --- | --- |
| trade_time | datetime | Y | 交易时间 |
| ts_code | str | Y | ETF代码 |
| vol | float | Y | 成交量（份） |
| num | int | Y | 成交笔数 |
| amount | float | Y | 成交金额（元） |
| price | float | Y | 最新价（元） |
| iopv | float | Y | 最近参考净值 |
| pre_iopv | float | Y | 前一日参考净值 |
| buy_num | int | Y | 申购笔数 |
| buy_vol | float | Y | 申购买量(份) |
| sell_num | int | Y | 赎回笔数 |
| sell_vol | float | Y | 赎回买量（份） |

### 代码示例

```
# 导入sdk包
import tushare as ts

# 配置凭据，如果已全局配置了，可以忽略。
ts.set_token('<--your-token-->')

# 获取接口实例
pro = ts.pro_api()

# 示例： 获取单个ETF（159103.SZ）的最新参考
df = pro.rt_etf_sz_iopv(ts_code="159103.SZ")
print(df)

# 示例： 获取两个ETF的最新参考（159103.SZ,159105.SZ）
df = pro.rt_etf_sz_iopv(ts_code="159103.SZ,159105.SZ")
print(df)

# 示例：获取深市ETF全部实时参考指标
df = pro.rt_etf_sz_iopv()

#示例：获取深市ETF指定指标的实时参考
df = pro.rt_etf_sz_iopv(fields='trade_time,ts_code,iopv,buy_num,buy_vol,sell_num,sell_vol')
print(df)
```

### 数据结果

```
             trade_time    ts_code    iopv  buy_num   buy_vol  sell_num  sell_vol
0    2026-03-20 10:27:27  161039.SZ  0.0000        0    0.0000         0    0.0000
1    2026-03-20 10:28:45  159003.SZ  0.0000        7    1.1101        18    3.3692
2    2026-03-20 10:28:48  159005.SZ  0.0000       26    5.3240         4    0.5903
3    2026-03-20 10:29:03  159102.SZ  0.7776        0    0.0000         0    0.0000
4    2026-03-20 10:29:09  159108.SZ  0.9792        1  100.0000         0    0.0000
..                   ...        ...     ...      ...       ...       ...       ...
923  2026-03-20 10:28:00  180302.SZ  0.0000        0    0.0000         0    0.0000
924  2026-03-20 10:29:09  180402.SZ  0.0000        0    0.0000         0    0.0000
925  2026-03-20 10:29:06  180606.SZ  0.0000        0    0.0000         0    0.0000
926  2026-03-20 10:29:06  180701.SZ  0.0000        0    0.0000         0    0.0000
927  2026-03-20 10:29:00  180901.SZ  0.0000        0    0.0000         0    0.0000
```

---

## 指数公司公告

### 接口介绍

接口：idx_anns
描述：获取指数公司披露的相关公告信息，包括中证指数、国证指数、恒生指数和华证指数的及时与历史公告信息，跟踪指数最新信息和发展方向。
限量：单次最大返回1000条数据，可根据日期循环提取
积分：需要6000积分可以调取，具体请参阅[积分获取办法](https://tushare.pro/document/1?doc_id=13)

### 输入参数

| 名称 | 类型 | 必选 | 描述 |
| --- | --- | --- | --- |
| ann_date | str | N | 公告日期（YYYYMMDD格式，下同） |
| start_date | str | N | 公告开始日期 |
| end_date | str | N | 公告结束日期 |
| src | str | N | 信息来源（中证指数、国证指数、恒生指数、华证指数） |

### 输出参数

| 名称 | 类型 | 默认显示 | 描述 |
| --- | --- | --- | --- |
| ann_date | str | Y | 公告日期 |
| title | str | Y | 标题 |
| url | str | Y | 链接 |
| source | str | Y | 来源 |
| type | str | Y | 类型(指数发布、指数修订、指数更名、其他） |

### 代码示例

```
# 拉取接口(idx_anns)数据
# 示例：获取2026年4月16日指数公司发布的指数公告
df = pro.idx_anns(ann_date='20260416')

#示例：获取中证指数公司发布的指数公告
df = pro.idx_anns(src='中证指数')

#示例：获取国证指数公司2026年1月以来发布的指数公告，并指定输出字段
df = pro.idx_anns(src='国证指数', start_date='20260101', fields='ann_date,title,type')
```

### 数据结果

```
   ann_date                           title                                                url source   type
0  20260420                 关于发布华证HALO指数的公告  https://www.chindices.com/news_detail.html?id=777   华证指数
1  20260417              恒生中国高股息率指数年度指数检讨结果  https://www.hsi.com.hk/static/uploads/contents...   恒生指数     其他
2  20260416                  关于调整三板指数样本股的公告  https://www.csindex.com.cn/#/about/newsDetail?...   中证指数   指数调样
3  20260415                  关于调整三板指数样本股的公告  https://www.csindex.com.cn/#/about/newsDetail?...   中证指数   指数调样
4  20260414                 关于终止计算发布3条指数的公告  http://www.cnindex.com.cn/zh_information/notic...   国证指数
5  20260414                  关于调整三板成指样本股的公告  https://www.csindex.com.cn/#/about/newsDetail?...   中证指数   指数调样
6  20260410             关于发布上证AAA综合债指数系列的公告  https://www.csindex.com.cn/#/about/newsDetail?...   中证指数  新指数发布
7  20260410          关于发布中证交易所AAA综合债指数系列的公告  https://www.csindex.com.cn/#/about/newsDetail?...   中证指数  新指数发布
8  20260410  关于终止计算、维护与发布中证公共卫生主题指数等2条指数的公告  https://www.csindex.com.cn/#/about/newsDetail?...   中证指数     其他
9  20260409                  关于调整三板指数样本股的公告  https://www.csindex.com.cn/#/about/newsDetail?...   中证指数   指数调样
```

---
