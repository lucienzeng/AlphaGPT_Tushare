"""统一质量检查：先留冲突证据再去重，不以下载成功代替数据可靠。"""
import hashlib
import numpy as np
import pandas as pd
from alphagpt.research.storage import dumps, now


def unique_rows(frame, keys):
    """完全相同的重复可消除；同键异值必须由来源修订处理，不能任取最后一行。"""
    if any(k not in frame for k in keys) or frame[keys].isna().any().any():
        raise ValueError(f"主键缺失：{keys}")
    identical = frame.drop_duplicates()
    conflicts = identical.loc[identical.duplicated(keys, keep=False)]
    if not conflicts.empty:
        raise ValueError("同键不同值冲突：" + dumps(conflicts.head(6).to_dict('records')))
    return identical.reset_index(drop=True)


def check_dates(frame, column):
    if column not in frame:
        raise ValueError(f"缺少日期 {column}")
    text = frame[column].astype(str)
    if not text.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all() or pd.to_datetime(text, format='%Y-%m-%d', errors='coerce').isna().any():
        raise ValueError(f"日期无效：{column}")


def finite(frame, columns, positive=False, nonnegative=False):
    for col in columns:
        if col not in frame:
            raise ValueError(f"缺少必要字段 {col}")
        v = pd.to_numeric(frame[col], errors='coerce')
        bad = ~np.isfinite(v)
        if positive:
            bad |= v.le(0)
        if nonnegative:
            bad |= v.lt(0)
        if bad.any():
            keys=[k for k in ['ts_code','trade_date'] if k in frame]
            examples=frame.loc[bad,keys].head(3).to_dict('records')
            raise ValueError(f"{col} 有 {int(bad.sum())} 行缺失、非有限或越界值；示例：{examples}")


def validate_bars(frame):
    if frame.empty:
        raise ValueError('行情为空')
    unique_rows(frame, ['ts_code', 'trade_date'])
    check_dates(frame, 'trade_date')
    finite(frame, ['open', 'high', 'low', 'close', 'settle'], positive=True)
    finite(frame, ['vol', 'oi'], nonnegative=True)
    bad = (frame.high.lt(frame.low) | frame.open.gt(frame.high) | frame.open.lt(frame.low)
           | frame.close.gt(frame.high) | frame.close.lt(frame.low))
    if bad.any():
        raise ValueError(f'行情有 {int(bad.sum())} 行OHLC关系异常')
    warnings = []
    if 'amount' not in frame or not np.isfinite(pd.to_numeric(frame['amount'], errors='coerce')).all():
        warnings.append('成交额缺失或非有限：禁用依赖成交额的派生特征，不填0')
    return dict(rows=len(frame), invalid=0, duplicates=int(frame.duplicated(['ts_code','trade_date']).sum()),
                warnings=warnings, units='价格元/吨，成交及持仓手，成交额万元；跨2020口径单独预热')


def validate_response(endpoint, frame):
    keys = {'fut_basic':['ts_code'], 'fut_trade_cal':['exchange','cal_date']}.get(endpoint, ['ts_code','trade_date'])
    frame = unique_rows(frame, keys)
    if endpoint == 'fut_basic':
        check_dates(frame, 'list_date'); check_dates(frame, 'delist_date')
        finite(frame, ['per_unit'], positive=True)
    elif endpoint == 'fut_trade_cal':
        check_dates(frame, 'cal_date')
        if not frame.is_open.isin([0,1]).all():
            raise ValueError('交易日历标志无效')
    else:
        check_dates(frame, 'trade_date')
        if endpoint == 'fut_daily':
            validate_bars(frame)
        elif endpoint == 'fut_mapping':
            if 'mapping_ts_code' not in frame or frame.mapping_ts_code.isna().any():
                raise ValueError('主力映射目标缺失')
        elif endpoint == 'ft_limit':
            finite(frame, ['up_limit','down_limit','m_ratio'], positive=True)
            if frame.up_limit.lt(frame.down_limit).any():
                raise ValueError('涨跌停上下界颠倒')
    return frame


def validate_dataset(data):
    report = validate_bars(data['bars'])
    mapping = validate_response('fut_mapping', data['mapping'])
    if mapping.trade_date.duplicated().any():
        raise ValueError('研究曲线每日映射不唯一')
    contracts = unique_rows(data['contracts'], ['ts_code'])
    finite(contracts, ['per_unit'], positive=True)
    for col in ['list_date','delist_date']:
        check_dates(contracts, col)
    if not set(mapping.mapping_ts_code).issubset(set(contracts.ts_code)):
        raise ValueError('映射包含未知真实合约')
    expected = pd.MultiIndex.from_arrays([mapping.trade_date, mapping.mapping_ts_code])
    for name in ['bars','limits']:
        frame = data[name]
        unique_rows(frame, ['trade_date','ts_code'])
        if len(expected.difference(pd.MultiIndex.from_frame(frame[['trade_date','ts_code']]))):
            raise ValueError(f'映射合约缺少{name}，不能伪装完整')
    validate_response('ft_limit', data['limits'])
    fees = data['fees']
    if not fees.empty:
        validate_response('fut_settle', fees)
    missing = pd.MultiIndex.from_frame(data['bars'][['trade_date','ts_code']]).difference(
        pd.MultiIndex.from_frame(fees[['trade_date','ts_code']]))
    report.update(settlement_missing_rows=len(missing),
                  settlement_policy='参数缺失不填0；固定成本可继续，历史手续费按实际订单严格检查')
    return report


def audit(store, subject, report, task=None, status='passed'):
    record = dict(subject=subject, status=status, task=task, checked_at=now(), **report)
    key = hashlib.sha256(dumps(record).encode()).hexdigest()[:24]
    store.put('quality_checks', key, record)
    return key


def reconcile(store, snapshot, official, source, task=None):
    """导入已统一单位的官方表，只记录差异，绝不覆盖研究数据。"""
    if not source.strip():
        raise ValueError('请注明官方文件来源/日期；不要把第三方转引当独立来源')
    keys = ['ts_code','trade_date']
    official = unique_rows(official, keys)
    check_dates(official, 'trade_date')
    columns = [c for c in ['open','high','low','close','settle','vol','oi','amount'] if c in official]
    if not columns or official.empty:
        raise ValueError('官方表为空或没有可核对字段')
    finite(official, columns)
    meta = store.get('snapshots', snapshot)
    local = store.read(meta['paths']['bars'])
    joined = official[keys+columns].merge(local[keys+columns], on=keys, how='left', suffixes=('_official','_local'), indicator=True)
    differences = []
    for row in joined.to_dict('records'):
        for col in columns:
            a, b = row[col+'_official'], row[col+'_local']
            # 不自动容忍一个价格跳动，来源舍入差异也保留证据供人工处理。
            if pd.isna(b) or a != b:
                differences.append({**{k:row[k] for k in keys}, 'field':col,'official':a,'local':b})
    return audit(store, snapshot, dict(rule='official_reconciliation', source=source,
                 checked_rows=len(official), differences=differences, difference_count=len(differences)),
                 task, 'passed' if not differences else 'review_required')
