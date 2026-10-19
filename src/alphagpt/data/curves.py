"""研究曲线与不可变复权主连；不修改原始行情，不用未来价差重写历史。"""
import hashlib
import pandas as pd
import numpy as np
from pathlib import Path
from alphagpt.research.storage import dumps, now

CURVE_VERSION = 'causal-ratio-v1'


def select_curve(data, code='CU.SHF'):
    """固定月份曲线也保留完整底表，只改变逐日选约映射。"""
    out = dict(data)
    mapping = data['mapping']
    if code in set(mapping.ts_code):
        out['mapping'] = mapping.loc[mapping.ts_code.eq(code)].copy()
    elif code in set(data['contracts'].ts_code):
        contract = data['contracts'].set_index('ts_code').loc[code]
        calendar = mapping[['trade_date']].drop_duplicates().sort_values('trade_date')
        calendar = calendar.loc[calendar.trade_date.between(str(contract.list_date), str(contract.delist_date))]
        out['mapping'] = calendar.assign(ts_code=code, mapping_ts_code=code)
    else:
        raise ValueError(f'所选研究曲线不存在：{code}')
    if out['mapping'].empty:
        raise ValueError('研究曲线没有可用交易日')
    return out


def build_curve_frame(data, mode='causal_ratio'):
    if mode not in ('causal_ratio', 'raw'):
        raise ValueError('未知价格曲线处理方式')
    mapping = data['mapping'].sort_values('trade_date')
    if mapping.trade_date.duplicated().any():
        raise ValueError('研究曲线每个交易日只能有一个映射')
    bars = data['bars'].set_index(['trade_date', 'ts_code'])
    if not bars.index.is_unique:
        raise ValueError('月份行情存在重复键')
    panel = mapping.merge(data['bars'], left_on=['trade_date','mapping_ts_code'],
                          right_on=['trade_date','ts_code'], suffixes=('_continuous',''),
                          how='left', validate='one_to_one').reset_index(drop=True)
    if panel[['open','high','low','close']].isna().any().any():
        raise ValueError('研究曲线映射缺少真实合约OHLC，不能填充')
    ratio, prior, since = 1.0, None, None
    factors, rolls, elapsed = [], [], []
    for row in panel.itertuples():
        switched = prior is not None and row.mapping_ts_code != prior.mapping_ts_code
        if switched and mode == 'causal_ratio':
            try:
                old = float(bars.loc[(prior.trade_date,prior.mapping_ts_code),'close'])
                new = float(bars.loc[(prior.trade_date,row.mapping_ts_code),'close'])
            except KeyError as e:
                raise ValueError('换月缺少前一交易日新旧合约价格，不能制造复权值') from e
            if not np.isfinite(old * new) or min(old, new) <= 0:
                raise ValueError('换月衔接价格必须为有限正数')
            ratio *= old / new
        # 首个观察点之前的切换未知，不能假设恰好在快照起点换月。
        since = 0 if switched else (since + 1 if since is not None else None)
        factors.append(ratio); rolls.append(int(switched)); elapsed.append(since)
        prior = row
    panel['adjustment'] = factors
    panel['is_roll'] = rolls
    panel['days_since_roll'] = pd.Series(elapsed, dtype='float64')
    for column in ['open','high','low','close']:
        panel['signal_'+column] = panel[column] * panel.adjustment
    expiries = data['contracts'].set_index('ts_code').delist_date
    panel['days_to_last_trade'] = (pd.to_datetime(panel.mapping_ts_code.map(expiries)) - pd.to_datetime(panel.trade_date)).dt.days
    if panel.days_to_last_trade.isna().any():
        raise ValueError('研究曲线缺少最后交易日')
    return panel


def prepare_curve(store, snapshot, data, code, mode, asof=None):
    if asof is not None:
        data = {k: v.loc[v.trade_date.le(asof)].copy() if isinstance(v,pd.DataFrame) and 'trade_date' in v else v.copy() for k,v in data.items()}
    selected = select_curve(data, code)
    panel = build_curve_frame(selected, mode)
    identity = {'snapshot':snapshot,'code':code,'mode':mode,'version':CURVE_VERSION,'asof':asof,
                'algorithm_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    key = 'curve_' + hashlib.sha256(dumps(identity).encode()).hexdigest()[:20]
    # 底快照不可变，曲线标识包含方法版本；已生成曲线绝不原地覆盖。
    if not store.get('curves',key):
        path = store.frame(f'curves/{key}/bars.parquet',panel)
        store.put('curves',key,{**identity,'path':path,'created':now(),'rows':len(panel),
            'file_sha256':hashlib.sha256((store.root/path).read_bytes()).hexdigest(),
            'start':panel.trade_date.min(),'end':panel.trade_date.max(),
            'semantics':'因果比例衔接，仅用于信号，成交盯市仍使用真实月份原价' if mode=='causal_ratio' else '原始价格；主连可能包含换月价差'})
    meta = store.get('curves',key)
    if hashlib.sha256((store.root/meta['path']).read_bytes()).hexdigest() != meta['file_sha256']:
        raise ValueError('派生曲线内容校验失败，拒绝读取被改写的曲线')
    selected['signal_curve'] = store.read(meta['path'])
    return selected, key
