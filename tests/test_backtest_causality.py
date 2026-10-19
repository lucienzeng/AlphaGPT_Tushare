"""防未来信息回归：改变执行日行情不能倒改预先确定的订单。"""
from dataclasses import asdict

import pandas as pd
import pytest

from alphagpt.backtest.futures import backtest
from alphagpt.research.config import BacktestConfig, ExperimentConfig
from alphagpt.research.storage import Store
from alphagpt.research.workflow import evaluate, execute
from tests.test_research import sample, Context


def test_open_and_same_day_margin_cannot_resize_opening_order(monkeypatch):
    import alphagpt.backtest.futures as engine
    data = sample(8, constant=True)
    dates = data['mapping'].trade_date.tolist()
    data['mapping']['mapping_ts_code'] = 'CU2401.SHF'
    data['limits']['m_ratio'] = 100
    monkeypatch.setattr(engine, 'signal_positions', lambda f, c, d: pd.Series(1, index=f.index))
    cfg = BacktestConfig(capital=5000, exposure=1, margin_cap=.2, fee=0, slippage_ticks=0)
    factor = pd.Series(1., index=dates)
    before, orders_before, _ = backtest(data, factor, cfg, dates[0], dates[2])
    altered = {k: v.copy() for k, v in data.items()}
    mask = altered['bars'].trade_date.eq(dates[2])
    altered['bars'].loc[mask, ['open', 'close', 'high', 'low', 'settle']] = 200.
    altered['bars'].loc[mask, ['vol', 'oi']] = 999999.
    altered['limits'].loc[altered['limits'].trade_date.eq(dates[2]), 'm_ratio'] = 80
    after, orders_after, _ = backtest(altered, factor, cfg, dates[0], dates[2])
    assert before.planned_quantity.tolist() == after.planned_quantity.tolist()
    assert orders_before.change.tolist() == orders_after.change.tolist() == [2]
    assert orders_before.reference_open.tolist() == [100.]
    assert orders_after.reference_open.tolist() == [200.]
    # 执行价格和盘后保证金可以变，预先下单的手数不能反向依赖它们。
    assert before.margin_ratio.iloc[-1] != after.margin_ratio.iloc[-1]


def test_executing_day_limit_can_reject_but_not_rewrite_plan(monkeypatch):
    import alphagpt.backtest.futures as engine
    data = sample(8, constant=True)
    dates = data['mapping'].trade_date.tolist()
    monkeypatch.setattr(engine, 'signal_positions', lambda f, c, d: pd.Series(1, index=f.index))
    data['limits'].loc[data['limits'].trade_date.eq(dates[2]), 'up_limit'] = 100
    daily, trades, _ = backtest(data, pd.Series(1., index=dates), BacktestConfig(), dates[0], dates[2])
    assert daily.planned_quantity.iloc[-1] > 0
    assert daily.quantity.iloc[-1] == 0 and trades.empty


@pytest.mark.parametrize('kind', ['retest', 'final_test'])
def test_task_entry_rejects_t1_before_loading_data(tmp_path, monkeypatch, kind):
    import alphagpt.research.workflow as workflow
    store = Store(tmp_path)
    cfg = ExperimentConfig('unused', '2023-01-01', '2023-06-30', '2023-09-30', '2023-12-31')
    store.put('experiments', 'parent', dict(config=asdict(cfg)))
    def forbidden(*a, **kw):
        pytest.fail('无效配置不应进入数据读取或回测')
    monkeypatch.setattr(workflow, 'evaluate', forbidden)
    changed = asdict(cfg.backtest)
    changed['decision_lag'] = 1
    with pytest.raises(ValueError, match='至少2|冻结参数'):
        execute(kind, dict(experiment='parent', backtest=changed), Context(store))
    assert not store.list('holdout_access')


def test_direct_evaluate_also_validates_delay(tmp_path):
    cfg = ExperimentConfig('missing', '2023-01-01', '2023-06-30', '2023-09-30', '2023-12-31',
                           backtest=BacktestConfig(decision_lag=1))
    store = Store(tmp_path)
    with pytest.raises(ValueError, match='至少2'):
        evaluate(store, cfg, {}, Context(store))


def test_late_margin_publication_rejected_by_engine():
    data = sample(8, constant=True)
    data['limits']['available_trade_date'] = '2029-01-01'
    dates = data['mapping'].trade_date.tolist()
    with pytest.raises(ValueError, match='尚不可用'):
        backtest(data, pd.Series(1., index=dates), BacktestConfig(), dates[0], dates[-1])


@pytest.mark.parametrize('params', [dict(tick_size=-10), dict(fallback_margin=0), dict(decision_lag=1.5)])
def test_invalid_execution_inputs_rejected(params):
    with pytest.raises(ValueError):
        BacktestConfig(**params).validate()
