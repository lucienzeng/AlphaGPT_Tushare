"""SQLite 迁移、分段原子提交及外部只读浏览的正确性。"""

from pathlib import Path
import sqlite3
import pandas as pd
import pytest
from alphagpt.data.sqlite import MarketData, TABLES
from alphagpt.research.storage import Store


def bars(price=100.0):
    return pd.DataFrame(
        {
            "ts_code": ["CU2401.SHF", "CU2401.SHF"],
            "trade_date": ["2024-01-02", "2024-01-03"],
            "close": [price, 101.0],
            "oi": pd.Series([None, 2.0], dtype="float64"),
        }
    )


def legacy(store, endpoint, symbol, frame):
    p = store.root / "cache" / endpoint / (symbol + ".parquet")
    p.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(p, index=False)
    return p


def test_migration_exact_idempotent_and_backup(tmp_path):
    s = Store(tmp_path)
    m = MarketData(s)
    p = legacy(s, "fut_daily", "CU2401.SHF", bars())
    original = p.read_bytes()
    s.cover("fut_daily", "CU2401.SHF", ["2024-01-02", "2024-01-10"])
    report = m.migrate_legacy()
    pd.testing.assert_frame_equal(m.read("fut_daily", "CU2401.SHF"), bars())
    assert s.covered("fut_daily", "CU2401.SHF") == {"2024-01-02", "2024-01-03"}
    assert Path(report["backup"], "research.sqlite").exists()
    assert Path(report["backup"], "cache/fut_daily/CU2401.SHF.parquet").read_bytes() == original
    m.write("fut_daily", "CU2401.SHF", bars(200.0))
    assert m.migrate_legacy() == report  # 不被遗留 Parquet 覆盖回旧值。
    assert m.read("fut_daily", "CU2401.SHF").close.iloc[0] == 200.0
    assert p.read_bytes() == original
    with s.connect() as db:
        assert all(
            db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (t,)).fetchone()
            for t, _, _ in TABLES.values()
        )
        assert db.execute('SELECT count(*) FROM "沪铜_月份合约行情"').fetchone()[0] == 2


def test_upsert_and_coverage_rollback_are_atomic(tmp_path):
    s = Store(tmp_path)
    m = MarketData(s)
    m.write("fut_daily", "CU2401.SHF", bars(), covered_days=["2024-01-02", "2024-01-03"])
    with s.connect() as db:
        db.execute(
            "CREATE TRIGGER reject_cover BEFORE INSERT ON coverage WHEN NEW.day='2024-01-04' BEGIN SELECT RAISE(ABORT,'模拟覆盖提交失败'); END"
        )
    incoming = bars(300.0)
    incoming.loc[1, "trade_date"] = "2024-01-04"
    with pytest.raises(sqlite3.IntegrityError, match="模拟覆盖"):
        m.write(
            "fut_daily",
            "CU2401.SHF",
            incoming,
            covered_days=["2024-01-04"],
            repair=("test", {"2024-01-04"}),
        )
    pd.testing.assert_frame_equal(m.read("fut_daily", "CU2401.SHF"), bars())
    assert s.get("repair_coverage", "test") is None
    assert "2024-01-04" not in s.covered("fut_daily", "CU2401.SHF")
    with s.connect() as db:
        db.execute("DROP TRIGGER reject_cover")
    m.write("fut_daily", "CU2401.SHF", incoming, covered_days=["2024-01-04"])
    assert len(m.read("fut_daily", "CU2401.SHF")) == 3
    assert m.read("fut_daily", "CU2401.SHF").close.iloc[0] == 300.0
    assert not (s.root / "cache").exists()  # 正常写入不再生成原始行情 Parquet。


def test_failed_migration_rolls_back_then_can_retry(tmp_path):
    s = Store(tmp_path)
    m = MarketData(s)
    legacy(s, "fut_daily", "CU2401.SHF", bars())
    bad = legacy(s, "fut_mapping", "CU.SHF", pd.DataFrame({"trade_date": ["2024-01-02"]}))
    s.cover("fut_daily", "CU2401.SHF", ["2024-01-10"])
    with pytest.raises(ValueError, match="主键"):
        m.migrate_legacy()
    assert m.read("fut_daily", "CU2401.SHF").empty
    assert s.covered("fut_daily", "CU2401.SHF") == {"2024-01-10"}
    with s.connect() as db:
        assert db.execute("SELECT count(*) FROM market_migrations").fetchone()[0] == 0
    pd.DataFrame(
        {"ts_code": ["CU.SHF"], "trade_date": ["2024-01-02"], "mapping_ts_code": ["CU2401.SHF"]}
    ).to_parquet(bad, index=False)
    assert m.migrate_legacy()["status"] == "succeeded"
    with s.connect() as db:
        r = db.execute('SELECT * FROM "沪铜_主连未复权行情"').fetchone()
        assert r["实际月份合约"] == "CU2401.SHF" and r["匹配状态"] == "已匹配"


def test_readonly_viewer_does_not_block_ingestion(tmp_path):
    s = Store(tmp_path)
    m = MarketData(s)
    m.write("fut_daily", "CU2401.SHF", bars())
    with sqlite3.connect((s.root / "research.sqlite").as_uri() + "?mode=ro", uri=True) as viewer:
        viewer.execute("BEGIN")
        assert (
            viewer.execute("SELECT close FROM daily_bars ORDER BY trade_date").fetchone()[0]
            == 100.0
        )
        m.write("fut_daily", "CU2401.SHF", bars(500.0))
        # 浏览事务有一致快照；刷新事务即可看到刚提交的新数据。
        assert (
            viewer.execute("SELECT close FROM daily_bars ORDER BY trade_date").fetchone()[0]
            == 100.0
        )
        viewer.commit()
        assert (
            viewer.execute("SELECT close FROM daily_bars ORDER BY trade_date").fetchone()[0]
            == 500.0
        )
        with pytest.raises(sqlite3.OperationalError):
            viewer.execute("DELETE FROM daily_bars")


def test_partial_columns_and_date_range_query(tmp_path):
    s = Store(tmp_path)
    m = MarketData(s)
    m.write("fut_daily", "CU2401.SHF", bars())
    m.write("fut_daily", "CU2401.SHF", bars(600.0).drop(columns="oi"))
    actual = m.read("fut_daily", "CU2401.SHF", start="2024-01-03", end="2024-01-03")
    assert len(actual) == 1 and actual.oi.iloc[0] == 2.0
    assert m.summary().行数.iloc[0] == 2


def test_wrong_contract_cannot_create_false_coverage(tmp_path):
    s = Store(tmp_path)
    m = MarketData(s)
    wrong = bars()
    wrong["ts_code"] = "CU2402.SHF"
    with pytest.raises(ValueError, match="不属于请求范围"):
        m.write("fut_daily", "CU2401.SHF", wrong, covered_days=["2024-01-02"])
    assert m.read("fut_daily", "CU2401.SHF").empty
    assert not s.covered("fut_daily", "CU2401.SHF")
