"""研究曲线、增强特征、输入时间隔离与开盘未来信息回归。"""
from dataclasses import asdict
import numpy as np
import pandas as pd
import pytest
from tests.test_research import sample, Context
from alphagpt.data.curves import select_curve, build_curve_frame, prepare_curve
from alphagpt.factor.research import features, expression, RAW_FEATURES
from alphagpt.factor.templates import TEMPLATES
from alphagpt.research.config import ExperimentConfig, BacktestConfig
from alphagpt.research.storage import Store
from alphagpt.research.workflow import research_data, check_factor_scope, mine
from alphagpt.backtest.futures import backtest


def prefix(data, end):
    return {k: v.loc[v.trade_date.le(end)].copy() if 'trade_date' in v else v.copy() for k,v in data.items()}


def test_adjusted_curve_uses_prior_day_roll_prices_and_is_prefix_invariant():
    data=sample(180)
    full=build_curve_frame(data)
    i=90
    old=data['mapping'].iloc[i-1].mapping_ts_code
    new=data['mapping'].iloc[i].mapping_ts_code
    b=data['bars'].set_index(['trade_date','ts_code'])
    prior,day=data['mapping'].iloc[i-1].trade_date,data['mapping'].iloc[i].trade_date
    expected=b.loc[(day,new),'close']/b.loc[(prior,new),'close']-1
    assert full.signal_close.pct_change().iloc[i]==pytest.approx(expected)
    raw_return=full.close.pct_change().iloc[i]
    assert abs(raw_return-expected)>0.1  # 合成换月价差不能变成信号暴涨。
    end=full.trade_date.iloc[100]
    pd.testing.assert_frame_equal(full.loc[full.trade_date.le(end)].reset_index(drop=True), build_curve_frame(prefix(data,end)))
    changed={k:v.copy() for k,v in data.items()}
    future=changed['bars'].trade_date.gt(end)
    changed['bars'].loc[future,['open','high','low','close','settle']]*=10
    altered=build_curve_frame(changed)
    pd.testing.assert_frame_equal(full.loc[:100],altered.loc[:100])


def test_monthly_curve_and_raw_direction_features():
    data=select_curve(sample(180),'CU2401.SHF')
    data['signal_curve']=build_curve_frame(data,'raw')
    f,p=features(data,version='futures-v2')
    assert set(RAW_FEATURES).issubset(f.columns) and len(f.columns)==27
    assert p.mapping_ts_code.eq('CU2401.SHF').all()
    pd.testing.assert_series_equal(p.close,p.signal_close,check_names=False)
    assert (p.adjustment==1).all()
    expected=p.close.pct_change(5)*p.oi_change5
    np.testing.assert_allclose(f.same_contract_price_oi_raw,expected,equal_nan=True)
    assert set(f.is_roll.unique())=={0}


def test_v2_future_perturbation_and_every_prefix_do_not_rewrite_history():
    data=sample(180);f,_=features(data,version='futures-v2')
    for n in [80,90,91,110,160]:
        cut=data['mapping'].trade_date.iloc[n]
        partial,_=features(prefix(data,cut),version='futures-v2')
        pd.testing.assert_frame_equal(f.loc[:cut],partial)
    modified={k:v.copy() for k,v in data.items()}
    cut=data['mapping'].trade_date.iloc[110]
    future=modified['bars'].trade_date.gt(cut)
    modified['bars'].loc[future,['open','high','low','close','settle','vol','oi']]*=17
    modified['mapping'].loc[modified['mapping'].trade_date.gt(cut),'mapping_ts_code']='CU2401.SHF'
    g,_=features(modified,version='futures-v2')
    pd.testing.assert_frame_equal(f.loc[:cut],g.loc[:cut])


def test_curve_artifact_is_immutable_and_development_cannot_read_test_rows(tmp_path):
    store=Store(tmp_path);data=sample(180)
    paths={k:store.frame('snapshots/test/'+k+'.parquet',v) for k,v in data.items()}
    store.put('snapshots','test',dict(paths=paths,start=data['mapping'].trade_date.iloc[0],end=data['mapping'].trade_date.iloc[-1]))
    end=data['mapping'].trade_date.iloc[120]
    cfg=ExperimentConfig('test',data['mapping'].trade_date.iloc[0],data['mapping'].trade_date.iloc[80],end,data['mapping'].trade_date.iloc[-1],feature_version='futures-v2')
    selected,key=research_data(store,cfg,cfg.valid_end)
    assert all(v.trade_date.max()<=end for v in selected.values() if 'trade_date' in v)
    path=store.root/store.get('curves',key)['path'];before=path.read_bytes()
    _,again=research_data(store,cfg,cfg.valid_end)
    _,full=prepare_curve(store,'test',data,'CU.SHF','causal_ratio')
    assert key==again and key!=full and path.read_bytes()==before


def test_open_execution_does_not_consult_end_of_day_total_volume(monkeypatch):
    import alphagpt.backtest.futures as module
    data=sample(20,constant=True);dates=data['mapping'].trade_date.tolist()
    monkeypatch.setattr(module,'signal_positions',lambda f,c,d:pd.Series(1,index=f.index))
    factor=pd.Series(1,index=dates);cfg=BacktestConfig(decision_lag=2)
    daily,trades,_=backtest(data,factor,cfg,dates[0],dates[-1])
    changed={k:v.copy() for k,v in data.items()};changed['bars']['vol']=0
    later,orders,_=backtest(changed,factor,cfg,dates[0],dates[-1])
    pd.testing.assert_frame_equal(daily,later)
    pd.testing.assert_frame_equal(trades,orders)
    assert (orders.decision_date<orders.trade_date).all()


def test_templates_parse_and_future_operations_cannot_be_called():
    data=sample(180);f,_=features(data,version='futures-v2')
    for template in TEMPLATES:
        v,_=expression(template['expression'],f)
        assert v.notna().sum()>50 and len(template['logic_zh'])>35
    for expr in ['ret20_raw.shift(-1)','ret20_raw.iloc[-1]','future(ret20_raw)','label','__import__("os")','ret20_raw.rolling(5,center=True)']:
        with pytest.raises((ValueError,SyntaxError)):expression(expr,f)
    cfg=ExperimentConfig('s','2023-01-01','2023-04-01','2023-06-01','2023-08-01',feature_version='futures-v2')
    with pytest.raises(ValueError,match='最多组合4'):check_factor_scope('ret5+ret20+ret60+trend20+trend60',cfg)


def test_v2_backtest_and_orders_are_prefix_invariant_when_future_changes():
    data=sample(180)
    f,_=features(data,version='futures-v2')
    dates=data['mapping'].trade_date.tolist();end=dates[140]
    cfg=BacktestConfig(decision_lag=2)
    daily,orders,_=backtest(data,f.ret20_raw,cfg,dates[90],end)
    changed={k:v.copy() for k,v in data.items()}
    later=changed['bars'].trade_date.gt(end)
    changed['bars'].loc[later,['open','high','low','close','settle','oi','vol']]*=9
    g,_=features(changed,version='futures-v2')
    other,executions,_=backtest(changed,g.ret20_raw,cfg,dates[90],end)
    pd.testing.assert_frame_equal(daily,other)
    pd.testing.assert_frame_equal(orders,executions)
    # 所有预测均在执行日之前产生，空账本也允许但本例确有成交。
    assert len(orders)>0 and (orders.decision_date<orders.trade_date).all()


def test_today_close_settlement_and_volume_cannot_change_today_open_order(monkeypatch):
    import alphagpt.backtest.futures as module
    data=sample(10,constant=True);dates=data['mapping'].trade_date.tolist()
    monkeypatch.setattr(module,'signal_positions',lambda f,c,d:pd.Series(1,index=f.index))
    factor=pd.Series(1,index=dates);cfg=BacktestConfig(decision_lag=2)
    day=dates[2]
    _,before,_=backtest(data,factor,cfg,dates[0],day)
    changed={k:v.copy() for k,v in data.items()}
    today=changed['bars'].trade_date.eq(day)
    changed['bars'].loc[today,['close','settle','high']]*=3
    changed['bars'].loc[today,'vol']=0
    _,after,_=backtest(changed,factor,cfg,dates[0],day)
    pd.testing.assert_frame_equal(before,after)


def test_new_visual_curve_reuses_same_adjustment_algorithm():
    from alphagpt.visualization.kline_view import build_candles, contract_options
    data=sample(180)
    options=contract_options(data['bars'],data['mapping'],data['contracts'])
    assert options[0]['code']=='CU.SHF::causal_ratio'
    candles=build_candles(data['bars'],data['mapping'],'CU.SHF::causal_ratio',contracts=data['contracts'])
    panel=build_curve_frame(data)
    assert len(candles)==len(panel)
    np.testing.assert_allclose([x['close'] for x in candles],panel.signal_close.round(2))


def test_missing_version_in_historical_config_stays_legacy():
    cfg=ExperimentConfig.from_dict(dict(snapshot='s',train_start='2020-01-01',train_end='2022-12-31',valid_end='2023-12-31',test_end='2024-12-31'))
    assert cfg.feature_version=='legacy-v1' and not cfg.use_templates
    assert ExperimentConfig('s','2020-01-01','2022-12-31','2023-12-31','2024-12-31').feature_version=='futures-v2'


def test_unavailable_template_feature_is_audited_not_a_task_failure(tmp_path,monkeypatch):
    import json
    import alphagpt.research.workflow as workflow
    data=sample(400);store=Store(tmp_path)
    paths={k:store.frame('snapshots/s/'+k+'.parquet',v) for k,v in data.items()}
    store.put('snapshots','s',dict(paths=paths,start='2023-07-01',end='2024-06-30'))
    original=workflow.features
    def limited(data,version='legacy-v1'):
        f,p=original(data,version=version)
        return f.drop(columns='vol_change'),p
    monkeypatch.setattr(workflow,'features',limited)
    class FakeModel:
        def __init__(self,*args):pass
        def call(self,*args):
            return json.dumps({'factors':[dict(name_zh='测试候选',expression='ret5 + trend60',logic_zh='基于短期与中期价格相对各自历史的偏离提出可证伪的方向假设，使用历史可得数据，在趋势反转和交易成本高时可能失效，仅用于离线工程测试。',market_regime='测试',failure_risks='测试',expected_direction=1)]})
    monkeypatch.setattr(workflow,'ModelClient',FakeModel)
    cfg=ExperimentConfig('s','2023-07-01','2023-10-31','2024-01-31','2024-06-30',count=1,use_templates=True)
    result=mine(asdict(cfg),Context(store))
    assert result['attempted']==1
    templates=[f for f in store.list('factors') if f.get('source')=='方案模板']
    assert len(templates)==8
    assert any(f['status']=='rejected' and f.get('reason') for f in templates)
