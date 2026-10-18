"""用真实已下载数据验收 SQLite 迁移；禁止网络请求和读取旧缓存。"""

from dataclasses import asdict
from pathlib import Path
import hashlib
import json
import pandas as pd
from alphagpt.data.futures import TushareSource, load_snapshot
from alphagpt.data.sqlite import MarketData, TABLES
from alphagpt.research.storage import Store, dumps, now, identifier
from alphagpt.research.config import load_credentials, DownloadConfig, ExperimentConfig
from alphagpt.research.jobs import Manager
from alphagpt.research.cli import wait
from alphagpt.research.workflow import version_info
from alphagpt.factor.research import features, expression
from alphagpt.backtest.futures import backtest


def main():
    load_credentials()
    store = Store()
    manager = Manager(store)
    output = store.root / "verification" / ("sqlite_acceptance_" + identifier("run") + ".json")
    result = {"started": now(), "status": "running", "checks": {}, "version": version_info()}
    original_reader = pd.read_parquet
    original_request = TushareSource.request

    def guarded(path, *args, **kwargs):
        if Path(path).is_relative_to(store.root / "cache"):
            raise AssertionError("不允许从旧缓存 Parquet 回退读取")
        return original_reader(path, *args, **kwargs)

    def blocked(*args, **kwargs):
        raise AssertionError("重复同步应为零请求，不允许访问外部 API")

    TushareSource.request = blocked
    pd.read_parquet = guarded
    try:
        market = MarketData(store)
        migration = market.migrate_legacy()
        result["migration"] = migration["id"]
        result["backup"] = migration.get("backup")
        protected = {
            p: hashlib.sha256(p.read_bytes()).hexdigest()
            for kind in ("snapshots", "experiments")
            for p in (store.root / kind).rglob("*")
            if p.is_file()
        }
        snapshot = next(
            s
            for s in store.list("snapshots")
            if s["start"] == "2024-01-01" and s["end"] == "2024-12-31"
        )
        params = asdict(DownloadConfig(snapshot["start"], snapshot["end"]))
        task = manager.submit("sync", params)
        synced = wait(store, task)
        assert synced["requests"] == 0 and synced["snapshot"] == snapshot["id"]
        result.update(sync_task=task, snapshot=snapshot["id"])
        result["checks"]["SQL取数且重复同步零请求"] = True
        result["checks"]["数据快照内容哈希不变"] = True
        frozen = load_snapshot(store, snapshot["id"])
        # 从主库重建同一快照范围，逐表核验原始字段/类型/数值。
        sql = {
            "contracts": market.read("fut_basic", "CU"),
            "mapping": market.read(
                "fut_mapping", "CU.SHF", snapshot["warmup_start"], snapshot["end"]
            ),
        }
        codes = frozen["contracts"].ts_code.tolist()
        sql["contracts"] = (
            sql["contracts"][sql["contracts"].ts_code.isin(codes)]
            .sort_values("ts_code")
            .reset_index(drop=True)
        )
        for kind, endpoint in (
            ("bars", "fut_daily"),
            ("limits", "ft_limit"),
            ("fees", "fut_settle"),
        ):
            sql[kind] = (
                pd.concat(
                    [
                        market.read(endpoint, c, snapshot["warmup_start"], snapshot["end"])
                        for c in codes
                    ],
                    ignore_index=True,
                )
                .sort_values(["trade_date", "ts_code"])
                .reset_index(drop=True)
            )
        for kind, frame in frozen.items():
            pd.testing.assert_frame_equal(frame, sql[kind], check_exact=True)
        f0, _ = features(frozen)
        f1, _ = features(sql)
        pd.testing.assert_frame_equal(f0, f1, check_exact=True)
        result["checks"]["SQL与冻结快照逐字段及因子值一致"] = True
        original_id = "eval_20261018_014309_dcf7b4c4"
        original = store.get("experiments", original_id)
        cfg = ExperimentConfig.from_dict(original["config"])
        factor = expression(original["factor"]["expression"], f1)[0]
        for name, part in original["segments"].items():
            daily, trades, metrics = backtest(
                sql,
                factor,
                cfg.backtest,
                part["start"],
                part["end"],
                original["factor"]["expected_direction"],
            )
            pd.testing.assert_frame_equal(daily, store.read(part["daily"]), check_exact=True)
            pd.testing.assert_frame_equal(trades, store.read(part["trades"]), check_exact=True)
        result["checks"]["既有开发实验逐日账本及成交完全一致"] = original_id
        assert all(hashlib.sha256(p.read_bytes()).hexdigest() == h for p, h in protected.items())
        result["checks"]["全部旧快照与实验文件未改变"] = len(protected)
        with store.connect() as db:
            assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            result["table_rows"] = {
                t: db.execute("SELECT count(*) FROM " + t).fetchone()[0]
                for t, _, _ in TABLES.values()
            }
            result["gap_rows"] = db.execute('SELECT count(*) FROM "期货_数据缺口"').fetchone()[0]
            result["views"] = [
                r[0]
                for r in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='view' ORDER BY name"
                )
            ]
        result["checks"]["SQLite完整性检查"] = "ok"
        result["status"] = "succeeded"
    except Exception as e:
        result.update(status="failed", error=str(e))
        raise
    finally:
        pd.read_parquet = original_reader
        TushareSource.request = original_request
        manager.close()
        result["finished"] = now()
        output.write_text(dumps(result), encoding="utf-8")
        (store.root / "verification" / "sqlite_acceptance_latest.json").write_text(
            dumps(result), encoding="utf-8"
        )
        print(dumps({"report": str(output), **result}), flush=True)


if __name__ == "__main__":
    main()
