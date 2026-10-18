"""真实端到端验收：重复同步→DeepSeek挖掘→成本重算→冻结测试→导出。"""

from dataclasses import asdict
import json
from .config import DownloadConfig, ExperimentConfig, BacktestConfig
from .storage import Store, dumps, identifier, now
from .workflow import export_experiment


def smoke(manager, store: Store, wait) -> dict:
    snapshots = store.list("snapshots")
    if not snapshots:
        raise ValueError("请先完成 sync，真实验收不使用合成数据")
    selected = snapshots[0]
    key = identifier("acceptance")
    report = {
        "id": key,
        "started": now(),
        "source": "真实 Tushare + DeepSeek",
        "snapshot": selected["id"],
        "tasks": [],
        "checks": {},
    }
    try:
        task = manager.submit("sync", asdict(DownloadConfig(selected["start"], selected["end"])))
        report["tasks"].append(task)
        duplicate = wait(store, task)
        if duplicate["requests"] != 0:
            raise AssertionError("重复同步发生请求，请检查缓存覆盖清单")
        report["checks"]["重复完整同步零请求"] = True
        # 在快照可研究区间按时间划分，不涉及指标选择；预热数据已在快照内。
        import pandas as pd

        mapping = store.read(selected["paths"]["mapping"])
        days = sorted(mapping.loc[mapping.trade_date.ge(selected["start"]), "trade_date"].tolist())
        cfg = ExperimentConfig(
            selected["id"],
            days[0],
            days[int(len(days) * 0.55)],
            days[int(len(days) * 0.78)],
            days[-1],
            rounds=1,
            count=3,
            backtest=BacktestConfig(),
        )
        config_path = store.root / "verification" / "smoke_config.json"
        config_path.parent.mkdir(exist_ok=True)
        config_path.write_text(dumps(asdict(cfg)), encoding="utf-8")
        task = manager.submit("mine", asdict(cfg))
        report["tasks"].append(task)
        mined = wait(store, task)
        report["checks"]["真实模型生成与回测"] = mined
        factors = [
            x
            for x in store.list("factors")
            if x.get("task") == task and x.get("round", 0) > 0 and x["status"] == "accepted"
        ]
        chosen = max(
            factors,
            key=lambda x: (
                x.get("valid_metrics", {}).get("sharpe")
                if x.get("valid_metrics", {}).get("sharpe") is not None
                else -1e100
            ),
        )
        original_id = chosen["experiment"]
        original = store.get("experiments", original_id)
        original_manifest = dumps(original)
        bt = asdict(cfg.backtest)
        bt["fee"] *= 2
        rerun_task = manager.submit("retest", {"experiment": original_id, "backtest": bt})
        report["tasks"].append(rerun_task)
        rerun = wait(store, rerun_task)
        assert dumps(store.get("experiments", original_id)) == original_manifest
        report["checks"]["成本重算不改原实验"] = rerun
        final_task = manager.submit("final_test", {"experiment": original_id})
        report["tasks"].append(final_task)
        tested = wait(store, final_task)
        report["checks"]["独立测试记录"] = tested
        report["factor"] = chosen
        report["validation_metrics"] = original["segments"]["valid"]["metrics"]
        report["test_metrics"] = store.get("experiments", tested["experiment"])["segments"]["test"][
            "metrics"
        ]
        report["roll_trades"] = sum(
            store.read(part["trades"])
            .get("reason", pd.Series(dtype=str))
            .str.contains("换月")
            .sum()
            for part in original["segments"].values()
        )
        if report["roll_trades"] <= 0:
            raise AssertionError("真实验收区间没有产生换月交易，需扩大区间验证")
        archive = store.root / "verification" / (key + ".zip")
        archive.write_bytes(export_experiment(store, original_id))
        report["export"] = str(archive)
        report["status"] = "succeeded"
    except Exception as e:
        report.update(status="failed", error=str(e))
        raise
    finally:
        report["finished"] = now()
        store.put("acceptance", key, report)
        directory = store.root / "verification"
        directory.mkdir(exist_ok=True)
        (directory / (key + ".json")).write_text(dumps(report), encoding="utf-8")
        text = "# 沪铜真实端到端验收\n\n" + "状态：" + report.get("status", "unknown") + "\n\n"
        text += (
            "```json\n"
            + json.dumps(json.loads(dumps(report)), ensure_ascii=False, indent=2)
            + "\n```\n"
        )
        (directory / (key + ".md")).write_text(text, encoding="utf-8")
        print(dumps(report), flush=True)
    return report
