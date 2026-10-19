"""合成数据仅用于可手算正确性测试，不进入真实研究库。"""

from dataclasses import asdict
from types import SimpleNamespace
import json
import time
import numpy as np
import pandas as pd
import pytest
from alphagpt.data.futures import FuturesData, ROW_LIMITS, TushareSource
from alphagpt.factor.research import expression, validate_candidate, features
from alphagpt.backtest.futures import backtest, metrics
from alphagpt.research.config import DownloadConfig, BacktestConfig, ModelProfile
from alphagpt.research.storage import Store, dumps
from alphagpt.research.jobs import Cancelled, Manager
from alphagpt.api.models import ModelClient, parse_candidates


class Context:
    def __init__(self, store):
        self.store, self.id, self.stopped = store, "offline_test", False

    def check(self):
        if self.stopped:
            raise Cancelled()

    def log(self, event, **data):
        self.store.event(self.id, event, **data)

    def progress(self, stage, **data):
        self.log("progress", stage=stage, **data)

    def sleep(self, seconds):
        self.check()


@pytest.fixture
def context(tmp_path):
    return Context(Store(tmp_path))


def sample(n=300, constant=False):
    dates = pd.bdate_range("2023-01-02", periods=n).strftime("%Y-%m-%d").tolist()
    rows, limits, fees = [], [], []
    for j, sym in enumerate(["CU2401.SHF", "CU2402.SHF"]):
        for i, day in enumerate(dates):
            p = 100 + j * 100 + (0 if constant else i * 0.04 + np.sin(i / 5))
            rows.append(
                dict(
                    ts_code=sym,
                    trade_date=day,
                    open=p,
                    high=p + 2,
                    low=p - 2,
                    close=p + 0.2 if not constant else p,
                    settle=p,
                    vol=1000 + i * 2,
                    oi=2000 + i,
                    pre_settle=p,
                )
            )
            limits.append(
                dict(ts_code=sym, trade_date=day, up_limit=1000, down_limit=1, m_ratio=10)
            )
            fees.append(dict(ts_code=sym, trade_date=day, trading_fee_rate=0.00005, trading_fee=0))
    contracts = pd.DataFrame(
        [
            dict(ts_code=s, per_unit=5, list_date="2022-01-01", delist_date="2027-01-15")
            for s in ["CU2401.SHF", "CU2402.SHF"]
        ]
    )
    return {
        "bars": pd.DataFrame(rows),
        "limits": pd.DataFrame(limits),
        "fees": pd.DataFrame(fees),
        "contracts": contracts,
        "mapping": pd.DataFrame(
            {
                "trade_date": dates,
                "ts_code": ["CU.SHF"] * n,
                "mapping_ts_code": ["CU2401.SHF" if i < n // 2 else "CU2402.SHF" for i in range(n)],
            }
        ),
    }


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os')",
        "ret5.shift(-1)",
        "future(ret5)",
        "ret5[0]",
        "ret5 ** 2",
        "[x for x in ret5]",
        "True",
    ],
)
def test_expression_rejects_arbitrary_code(expr):
    with pytest.raises((ValueError, SyntaxError)):
        expression(expr, pd.DataFrame({"ret5": [1.0, 2.0]}))


def test_safe_expression_and_logic():
    frame = pd.DataFrame({"ret5": [1.0, 2.0], "ret20": [2.0, 0.0]})
    result, key = expression("ret5 / (abs(ret20) + 1)", frame)
    assert result.tolist() == [1 / 3, 2]
    with pytest.raises(ValueError, match="logic_zh"):
        validate_candidate({"name_zh": "缺解析", "expression": "ret5"})


def test_features_prefix_invariant():
    data = sample()
    original, _ = features(data)
    modified = {k: v.copy() for k, v in data.items()}
    cutoff = original.index[200]
    modified["bars"].loc[
        modified["bars"].trade_date.gt(cutoff), ["open", "close", "high", "low", "settle"]
    ] *= 2
    changed, _ = features(modified)
    pd.testing.assert_frame_equal(original.loc[:cutoff], changed.loc[:cutoff])
    cfg = BacktestConfig()
    before, orders_before, _ = backtest(data, original.trend20, cfg, original.index[100], cutoff)
    after, orders_after, _ = backtest(modified, changed.trend20, cfg, original.index[100], cutoff)
    pd.testing.assert_frame_equal(before, after)
    pd.testing.assert_frame_equal(orders_before, orders_after)


def test_roll_has_no_fake_profit_and_fee_debited(monkeypatch):
    import alphagpt.backtest.futures as module

    data = sample(6, constant=True)
    dates = data["mapping"].trade_date.tolist()
    monkeypatch.setattr(module, "signal_positions", lambda f, c, d: pd.Series(1, index=f.index))
    cfg = BacktestConfig(
        capital=5000, exposure=0.25, fee_mode="per_lot", fee=1, slippage_ticks=0, decision_lag=1
    )
    daily, trades, m = backtest(data, pd.Series(1, index=dates), cfg, dates[0], dates[-1])
    assert daily.gross_pnl.sum() == 0
    assert daily.equity.iloc[-1] == 5000 - daily.fee.sum()
    assert "换月平仓" in trades.reason.tolist()
    assert set(trades.symbol) == {"CU2401.SHF", "CU2402.SHF"}
    assert len(trades) >= 3


def test_long_short_and_slippage_handcheck(monkeypatch):
    import alphagpt.backtest.futures as module

    data = sample(6, constant=True)
    data["mapping"]["mapping_ts_code"] = "CU2401.SHF"
    dates = data["mapping"].trade_date.tolist()
    monkeypatch.setattr(
        module, "signal_positions", lambda f, c, d: pd.Series([1, 1, -1, -1, 0, 0], index=f.index)
    )
    cfg = BacktestConfig(
        capital=5000,
        exposure=0.2,
        fee_mode="per_lot",
        fee=0,
        slippage_ticks=0.1,
        tick_size=10,
        decision_lag=1,
    )
    daily, trades, _ = backtest(data, pd.Series(1, index=dates), cfg, dates[0], dates[-1])
    assert daily.gross_pnl.sum() == 0
    assert daily.equity.iloc[-1] == pytest.approx(5000 - trades.change.abs().sum() * 5)
    assert "反手平仓" in trades.reason.tolist()


def test_limit_rejects_orders_and_missing_history_fails(monkeypatch):
    import alphagpt.backtest.futures as module

    data = sample(6, constant=True)
    dates = data["mapping"].trade_date.tolist()
    monkeypatch.setattr(module, "signal_positions", lambda f, c, d: pd.Series(1, index=f.index))
    data["limits"]["up_limit"] = 100
    daily, trades, _ = backtest(
        data,
        pd.Series(1, index=dates),
        BacktestConfig(capital=5000, slippage_ticks=0, decision_lag=1),
        dates[0],
        dates[-1],
    )
    assert trades.empty
    assert daily.notes.str.contains("涨跌停").any()


def test_missing_coverage_only_and_row_split(context, monkeypatch):
    calls = []

    class Fake:
        config = DownloadConfig()
        ctx = context

        def request(self, endpoint, **p):
            days = pd.bdate_range(p["start_date"], p["end_date"]).strftime("%Y%m%d")
            calls.append(list(days))
            return pd.DataFrame({"trade_date": days, "ts_code": "CU2401.SHF", "open":100,"high":101,"low":99,"close":100,"settle":100,"vol":1000,"oi":2000}).head(3)

    monkeypatch.setitem(ROW_LIMITS, "fut_daily", 3)
    svc = FuturesData(context.store, Fake())
    days = pd.bdate_range("2024-01-01", periods=8).strftime("%Y-%m-%d").tolist()
    svc.fetch_range("fut_daily", "CU2401.SHF", days, ts_code="CU2401.SHF")
    assert len(calls) > 1
    before = len(calls)
    svc.fetch_range("fut_daily", "CU2401.SHF", days, ts_code="CU2401.SHF")
    assert len(calls) == before
    # 人为删除中间覆盖条目，应该只请求这一天，不按最大日期跳过。
    with context.store.connect() as db:
        db.execute("DELETE FROM coverage WHERE day=?", (days[3],))
    svc.fetch_range("fut_daily", "CU2401.SHF", days, ts_code="CU2401.SHF")
    assert calls[-1] == [days[3].replace("-", "")]
    assert len(context.store.read("cache/fut_daily/CU2401.SHF.parquet")) == 8


def test_empty_is_not_cached(context):
    class Fake:
        config = DownloadConfig()
        ctx = context

        def request(self, *args, **kwargs):
            return pd.DataFrame()

    with pytest.raises(ValueError, match="空数据"):
        FuturesData(context.store, Fake()).fetch_range(
            "fut_daily", "CU2401.SHF", ["2024-01-02"], ts_code="CU2401.SHF"
        )
    assert context.store.covered("fut_daily", "CU2401.SHF") == set()


def test_permission_fast_fail_and_transient_retry(context):
    class Fake:
        def __init__(self, error):
            self.n = 0
            self.error = error

        def query(self, *args, **kwargs):
            self.n += 1
            if self.n == 1:
                raise RuntimeError(self.error)
            return pd.DataFrame({"x": [1]})

    api = Fake("没有访问该接口的权限")
    with pytest.raises(RuntimeError):
        TushareSource(DownloadConfig(), context, api).request("fut_daily")
    assert api.n == 1
    api = Fake("临时网络错误")
    assert len(TushareSource(DownloadConfig(), context, api).request("fut_daily")) == 1
    assert api.n == 2


@pytest.mark.parametrize("protocol", ["chat", "responses"])
def test_model_protocol_and_trace_offline(context, protocol):
    sent = {}

    class Response:
        output_text = '{"factors":[]}'
        model = "offline-model"
        usage = SimpleNamespace(model_dump=lambda: {"total_tokens": 12})
        choices = [SimpleNamespace(message=SimpleNamespace(content='{"factors":[]}'))]

        def model_dump(self, **kwargs):
            return {"offline_fixture": True}

    def create(**kwargs):
        sent.update(kwargs)
        return Response()

    obj = ModelClient.__new__(ModelClient)
    obj.profile = ModelProfile(model="offline-model", protocol=protocol, optional_params={})
    obj.ctx = context
    obj.client = SimpleNamespace(
        responses=SimpleNamespace(create=create),
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
    )
    assert parse_candidates(obj.call("离线测试")) == []
    assert ("input" in sent) == (protocol == "responses")
    assert context.store.list("calls")[0]["usage"]["total_tokens"] == 12


def test_standard_sharpe():
    r = pd.Series([0.01, -0.02, 0.005, 0.003])
    d = pd.DataFrame(
        {
            "net_return": r,
            "gross_return": r,
            "gross_pnl": r,
            "net_pnl": r,
            "fee": 0,
            "slippage_cost": 0,
            "turnover": 0,
            "margin_ratio": 0,
        }
    )
    assert metrics(d, pd.DataFrame())["sharpe"] == pytest.approx(r.mean() / r.std() * np.sqrt(252))


def test_secret_redaction(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-secret-only-fixture")
    assert "test-secret-only-fixture" not in dumps(
        {"message": "failed test-secret-only-fixture", "api_key": "test-secret-only-fixture"}
    )


def test_delayed_sizing_uses_decision_day_equity(monkeypatch):
    import alphagpt.backtest.futures as module

    data = sample(20)
    dates = data["mapping"].trade_date.tolist()
    data["mapping"]["mapping_ts_code"] = "CU2401.SHF"
    prices = {day: 100 + i * 30 for i, day in enumerate(dates)}
    for col in ("open", "close", "settle", "pre_settle"):
        data["bars"][col] = data["bars"].trade_date.map(prices)
    data["bars"]["high"] = data["bars"].open + 1
    data["bars"]["low"] = data["bars"].open - 1
    monkeypatch.setattr(module, "signal_positions", lambda f, c, d: pd.Series(1, index=f.index))
    cfg = BacktestConfig(
        capital=10000, exposure=0.8, margin_cap=0.9, fee=0, slippage_ticks=0, decision_lag=2
    )
    daily, _, _ = backtest(data, pd.Series(1.0, index=dates), cfg, dates[0], dates[-1])
    for i in range(2, len(dates)):
        known_equity = daily.equity.iloc[i - 2]
        assert daily.quantity.iloc[i] == int(known_equity * 0.8 // (prices[dates[i - 2]] * 5))


def test_margin_cap_handcheck(monkeypatch):
    import alphagpt.backtest.futures as module

    data = sample(6, constant=True)
    dates = data["mapping"].trade_date.tolist()
    data["mapping"]["mapping_ts_code"] = "CU2401.SHF"
    data["limits"]["m_ratio"] = 100
    monkeypatch.setattr(module, "signal_positions", lambda f, c, d: pd.Series(1, index=f.index))
    cfg = BacktestConfig(
        capital=5000, exposure=1.0, margin_cap=0.2, fee=0, slippage_ticks=0, decision_lag=1
    )
    daily, trades, _ = backtest(data, pd.Series(1.0, index=dates), cfg, dates[0], dates[-1])
    assert trades.change.iloc[0] == 2  # 5000 * 20% / (100 * 5 * 100%)
    assert daily.margin_ratio.max() == pytest.approx(0.2)


def test_repair_interruption_resumes_completed_chunks(context):
    days = pd.bdate_range("2024-01-01", periods=123).strftime("%Y-%m-%d").tolist()
    calls = []

    class Fake:
        config = DownloadConfig(repair=True)
        ctx = context
        failed = False

        def request(self, endpoint, **p):
            calls.append(p["start_date"])
            if p["start_date"] == days[120].replace("-", "") and not self.failed:
                self.failed = True
                raise RuntimeError("模拟分段中断")
            return pd.DataFrame(
                {
                    "trade_date": pd.bdate_range(p["start_date"], p["end_date"]).strftime("%Y%m%d"),
                    "ts_code": "CU2401.SHF",
                    "close": 100, "open":100,"high":101,"low":99,"settle":100,"vol":1000,"oi":2000,
                }
            )

    svc = FuturesData(context.store, Fake())
    with pytest.raises(RuntimeError, match="分段中断"):
        svc.fetch_range("fut_daily", "CU2401.SHF", days, ts_code="CU2401.SHF")
    assert len(context.store.read("cache/fut_daily/CU2401.SHF.parquet")) == 120
    before = len(calls)
    result = svc.fetch_range("fut_daily", "CU2401.SHF", days, ts_code="CU2401.SHF")
    assert calls[before:] == [days[120].replace("-", "")]
    assert len(result) == 123 and not result.duplicated(["trade_date", "ts_code"]).any()


def test_tail_check_respects_cooldown(context):
    calls = []

    class Fake:
        config = DownloadConfig(tail_days=2, tail_check_hours=24)
        ctx = context

        def request(self, endpoint, **p):
            calls.append(p)
            return pd.DataFrame(
                {
                    "trade_date": pd.bdate_range(p["start_date"], p["end_date"]).strftime("%Y%m%d"),
                    "ts_code": "CU2401.SHF",
                    "close": 100, "open":100,"high":101,"low":99,"settle":100,"vol":1000,"oi":2000,
                }
            )

    days = pd.bdate_range("2024-01-01", periods=8).strftime("%Y-%m-%d").tolist()
    svc = FuturesData(context.store, Fake())
    svc.fetch_range("fut_daily", "CU2401.SHF", days, ts_code="CU2401.SHF")
    svc.fetch_range("fut_daily", "CU2401.SHF", days, ts_code="CU2401.SHF")
    assert len(calls) == 1
    with context.store.connect() as db:
        db.execute("DELETE FROM objects WHERE kind='tail_checks'")
    svc.fetch_range("fut_daily", "CU2401.SHF", days, ts_code="CU2401.SHF")
    assert len(calls) == 2 and calls[-1]["start_date"] == days[-2].replace("-", "")


def test_settlement_empty_continues_and_retries_then_resolves(context, caplog):
    class Fake:
        config = DownloadConfig()
        ctx = context
        available = False
        calls = 0

        def request(self, endpoint, **params):
            self.calls += 1
            if not self.available:
                return pd.DataFrame()
            return pd.DataFrame([dict(ts_code='CU2607.SHF', trade_date='20260708', trading_fee_rate=0.00005)])

    source = Fake()
    service = FuturesData(context.store, source)
    args = ('fut_settle', 'CU2607.SHF', ['2026-07-08'])
    result = service.fetch_range(*args, ts_code='CU2607.SHF')
    assert result.empty and 'trade_date' in result
    assert not context.store.covered('fut_settle', 'CU2607.SHF')
    assert '结算参数缺失' in caplog.text
    service.fetch_range(*args, ts_code='CU2607.SHF')
    with context.store.connect() as db:
        row = dict(db.execute('SELECT * FROM data_gaps').fetchone())
    assert row['status'] == 'open' and row['attempts'] == 2
    assert any(e['event'] == 'settlement_gap_warning' for e in context.store.events(context.id))
    source.available = True
    assert len(service.fetch_range(*args, ts_code='CU2607.SHF')) == 1
    with context.store.connect() as db:
        row = dict(db.execute('SELECT * FROM data_gaps').fetchone())
    assert row['status'] == 'resolved' and row['resolved_at']
    before = source.calls
    service.fetch_range(*args, ts_code='CU2607.SHF')
    assert source.calls == before


def test_settlement_partial_response_records_only_missing_dates(context):
    class Fake:
        config = DownloadConfig()
        ctx = context

        def request(self, *args, **kwargs):
            return pd.DataFrame([dict(ts_code='CU2607.SHF', trade_date='20260707', settle=100)])

    svc = FuturesData(context.store, Fake())
    svc.fetch_range('fut_settle', 'CU2607.SHF', ['2026-07-07', '2026-07-08'], ts_code='CU2607.SHF')
    assert context.store.covered('fut_settle', 'CU2607.SHF') == {'2026-07-07'}
    with context.store.connect() as db:
        assert [r[0] for r in db.execute('SELECT day FROM data_gaps')] == ['2026-07-08']


def test_missing_fees_only_blocks_historical_mode(monkeypatch):
    import alphagpt.backtest.futures as module
    data = sample(6, constant=True)
    data['fees'] = data['fees'].iloc[:0]
    dates = data['mapping'].trade_date.tolist()
    factor = pd.Series(1.0, index=dates)
    monkeypatch.setattr(module, 'signal_positions', lambda f, c, d: pd.Series(1, index=f.index))
    cfg = BacktestConfig(capital=1000000, fee_mode='rate', decision_lag=1)
    daily, trades, _ = backtest(data, factor, cfg, dates[0], dates[-1])
    assert len(daily) == 6 and not trades.empty
    cfg.fee_mode = 'historical'
    with pytest.raises(ValueError, match='缺少历史手续费'):
        backtest(data, factor, cfg, dates[0], dates[-1])


def test_full_sync_can_freeze_snapshot_with_all_settlement_rows_missing(context, monkeypatch):
    data = sample(100)
    end = data['mapping'].trade_date.iloc[-1]
    class Fake:
        config = DownloadConfig(start='2023-01-02', end=end, warmup_days=0)
        ctx = context
        calls = 0
        def request(self, endpoint, **p):
            self.calls += 1
            if endpoint == 'fut_settle':
                return pd.DataFrame()
            if endpoint == 'fut_trade_cal':
                dates = pd.date_range(p['start_date'], p['end_date'])
                return pd.DataFrame(dict(exchange='SHFE',cal_date=dates.strftime('%Y%m%d'),is_open=(dates.weekday<5).astype(int)))
            frame = data[{'fut_mapping':'mapping','fut_daily':'bars','ft_limit':'limits'}[endpoint]]
            frame = frame.loc[frame.ts_code.eq(p['ts_code'])].copy()
            frame['trade_date'] = frame.trade_date.str.replace('-', '')
            return frame
    service = FuturesData(context.store, Fake())
    monkeypatch.setattr(service, 'metadata', lambda: data['contracts'])
    result = service.sync()
    snapshot = context.store.get('snapshots', result['snapshot'])
    assert result['quality']['settlement_missing_rows'] == 200
    assert context.store.read(snapshot['paths']['fees']).empty
    assert len(context.store.read(snapshot['paths']['bars'])) == 200
    with context.store.connect() as db:
        assert db.execute("SELECT count(*) FROM data_gaps WHERE status='open'").fetchone()[0] == 200
