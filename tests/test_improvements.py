"""质量拦截、不可变版本、开发隔离和预算的可证伪测试。"""
from dataclasses import asdict
import hashlib
import json
import numpy as np
import pandas as pd
import pytest
from tests.test_research import sample, Context
from alphagpt.data.quality import validate_bars, validate_response, validate_dataset, reconcile
from alphagpt.data.futures import FuturesData, load_snapshot
from alphagpt.data.sqlite import MarketData
from alphagpt.data.curves import prepare_curve
from alphagpt.factor.research import formula_explanation
from alphagpt.research.config import ExperimentConfig, BacktestConfig, DownloadConfig
from alphagpt.research.storage import Store
from alphagpt.research.protocol import record_access, reserve_trial, availability_check


@pytest.mark.parametrize('field,value',[('vol',np.nan),('oi',np.inf),('close',np.inf),('vol',-1),('trade_date','2023-02-30')])
def test_bad_data_cannot_pass_quality(field,value):
    bars=sample(3)['bars']
    if field != 'trade_date':bars[field]=bars[field].astype(float)
    bars.loc[0,field]=value
    with pytest.raises(ValueError):validate_bars(bars)


def test_conflicting_response_is_audited_and_not_covered(tmp_path):
    store=Store(tmp_path);ctx=Context(store)
    bars=sample(1)['bars'].iloc[:1].copy()
    other=bars.copy();other['close']+=1
    class Source:
        config=DownloadConfig()
        def request(self,*args,**kwargs):
            f=pd.concat([bars,other]);f['trade_date']=f.trade_date.str.replace('-','')
            return f
    source=Source();source.ctx=ctx
    with pytest.raises(ValueError,match='同键不同值'):
        FuturesData(store,source).fetch_range('fut_daily','CU2401.SHF',['2023-01-02'])
    assert not store.covered('fut_daily','CU2401.SHF')
    assert store.list('quality_checks')[0]['status']=='failed'


def test_source_revisions_keep_old_value_and_unknown_publication(tmp_path):
    store=Store(tmp_path);market=MarketData(store)
    bars=sample(2)['bars'].iloc[:2]
    market.write('fut_daily','CU2401.SHF',bars)
    changed=bars.copy();changed['close']+=.1
    market.write('fut_daily','CU2401.SHF',changed)
    revisions=store.list('source_revisions')
    assert len(revisions)==2 and revisions[0]['published_at'] is None
    assert revisions[0]['prior_rows'][0]['close']==bars.close.iloc[0]
    pd.testing.assert_frame_equal(market.read('fut_daily','CU2401.SHF'),changed.reset_index(drop=True))


def snapshot(store,data,key='s'):
    paths={k:store.frame(f'snapshots/{key}/{k}.parquet',v) for k,v in data.items()}
    store.put('snapshots',key,dict(start='2023-07-01',end='2024-06-30',paths=paths,
        file_hashes={k:hashlib.sha256((store.root/p).read_bytes()).hexdigest() for k,p in paths.items()}))


def test_snapshot_and_curve_tampering_rejected(tmp_path):
    store=Store(tmp_path);data=sample(100);snapshot(store,data)
    _,key=prepare_curve(store,'s',data,'CU.SHF','causal_ratio')
    curve=store.root/store.get('curves',key)['path']
    curve.write_bytes(b'tampered')
    with pytest.raises(ValueError,match='内容校验失败'):prepare_curve(store,'s',data,'CU.SHF','causal_ratio')
    raw=store.root/store.get('snapshots','s')['paths']['bars'];raw.write_bytes(b'tampered')
    with pytest.raises(ValueError,match='内容校验失败'):load_snapshot(store,'s')


def test_official_reconciliation_records_difference_without_overwrite(tmp_path):
    store=Store(tmp_path);data=sample(100);snapshot(store,data)
    official=data['bars'].iloc[:3][['ts_code','trade_date','close']].copy()
    official.loc[0,'close']+=10
    before=(store.root/store.get('snapshots','s')['paths']['bars']).read_bytes()
    key=reconcile(store,'s',official,'上期所人工导入测试文件')
    report=store.get('quality_checks',key)
    assert report['status']=='review_required' and report['difference_count']==1
    assert before==(store.root/store.get('snapshots','s')['paths']['bars']).read_bytes()


def test_exposure_survives_other_snapshot_task_and_legacy_records(tmp_path):
    store=Store(tmp_path)
    assert record_access(store,'a','valid','2024-01-01','2024-03-31')['independent']
    state=record_access(store,'b','valid','2024-02-01','2024-04-30')
    assert not state['independent']
    store.put('test_access','old',dict(config=dict(snapshot='different',valid_end='2023-10-01',test_end='2023-12-31')))
    assert not record_access(store,'c','test','2023-11-01','2023-12-31')['independent']


def test_trial_budget_cannot_reset_and_delayed_publication_rejected(tmp_path):
    store=Store(tmp_path)
    reserve_trial(store,'p','f1','t1',1,'ret5')
    reserve_trial(store,'p','f1','t1',1,'ret5')
    with pytest.raises(ValueError,match='累计候选预算'):reserve_trial(store,'p','f2','t2',1,'ret20')
    data=sample(10);data['mapping']['available_trade_date']='2029-01-01'
    with pytest.raises(ValueError,match='尚不可用'):availability_check(data,2)
    data=sample(10);data['mapping']['available_at']='2029-01-01T12:00:00+08:00'
    with pytest.raises(ValueError,match='拒绝未来信息'):availability_check(data,2)


def test_typed_explanation_and_window_boundaries():
    text=formula_explanation('ret20_raw + ret20')
    assert '输入均为标准分' not in text
    assert '类型：原始值' in text and '类型：历史标准分' in text
    for window in [10,19]:
        with pytest.raises(ValueError):BacktestConfig(signal_window=window).validate()
    BacktestConfig(signal_window=20).validate()
    with pytest.raises(ValueError):BacktestConfig(fee=float('nan')).validate()


def test_missing_price_limit_cannot_bypass_execution(monkeypatch):
    import alphagpt.backtest.futures as engine
    data=sample(10)
    data['limits']['up_limit']=np.nan
    monkeypatch.setattr(engine,'signal_positions',lambda f,c,d:pd.Series(1,index=f.index))
    with pytest.raises(ValueError,match='拒绝用NaN'):
        engine.backtest(data,pd.Series(1,index=data['mapping'].trade_date),BacktestConfig(),
                        data['mapping'].trade_date.iloc[0],data['mapping'].trade_date.iloc[-1])


def test_validation_changes_cannot_change_generation_prompts(tmp_path,monkeypatch):
    import alphagpt.research.workflow as w
    prompts=[]
    class Model:
        def __init__(self,*args):pass
        def call(self,prompt,*args):
            prompts.append(prompt)
            return json.dumps({'factors':[dict(name_zh='隔离测试',expression='ret5 * tanh(volume_ratio)',
                logic_zh='通过价格相对历史强弱与成交活跃度组合提出可证伪假设，成交项可能变号，不能理解成正向确认；行情突变或成本过高可能使其失效，仅用于验证历史隔离。',
                expected_direction=1,market_regime='测试',failure_risks='测试')]})
    monkeypatch.setattr(w,'ModelClient',Model)
    for changed in [False,True]:
        store=Store(tmp_path/str(changed));data=sample(400)
        if changed:
            mask=data['bars'].trade_date.gt('2023-10-31')
            data['bars'].loc[mask,['open','high','low','close','settle']]*=3
            data['bars'].loc[mask,['vol','oi']]*=7
        snapshot(store,data)
        cfg=ExperimentConfig('s','2023-07-01','2023-10-31','2024-01-31','2024-06-30',rounds=2,count=1,random_controls=0)
        w.mine(asdict(cfg),Context(store))
    assert len(prompts)==4
    assert prompts[0]==prompts[2] and prompts[1]==prompts[3]
    assert 'valid_metrics' not in prompts[1]
