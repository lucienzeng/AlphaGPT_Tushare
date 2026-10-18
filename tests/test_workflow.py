from dataclasses import asdict
import json
import threading
import time
from pathlib import Path
import pandas as pd
import pytest
from tests.test_research import sample, Context
from alphagpt.research.storage import Store
from alphagpt.research.config import ExperimentConfig, BacktestConfig
from alphagpt.research.workflow import mine, execute, export_experiment
from alphagpt.research.jobs import Manager


def test_complete_offline_pipeline_and_frozen_test(tmp_path, monkeypatch):
    import alphagpt.research.workflow as workflow

    store = Store(tmp_path)
    data = sample(400)
    paths = {k: store.frame(f"snapshots/offline/{k}.parquet", v) for k, v in data.items()}
    store.put(
        "snapshots",
        "offline",
        {
            "start": "2023-07-01",
            "end": "2024-06-30",
            "paths": paths,
            "source": "明确标记的合成测试数据",
        },
    )
    prompts = []

    class FakeModel:
        def __init__(self, *args):
            pass

        def call(self, prompt, *args):
            prompts.append(prompt)
            exp = (
                "trend20 + 0.3 * volume_ratio"
                if len(prompts) == 1
                else "reversal + 0.2 * oi_change5"
            )
            return json.dumps(
                {
                    "factors": [
                        {
                            "name_zh": "离线候选",
                            "expression": exp,
                            "logic_zh": "此为离线合成数据测试候选。结合价格动量及相对成交和持仓结构提出可证伪的预测假设，正向预期仅来自事前约定。市场发生反转或交易成本过高时可能失效，测试成功不代表真实盈利。",
                            "market_regime": "测试",
                            "failure_risks": "合成数据不能用于研究结论",
                            "expected_direction": 1,
                        }
                    ]
                }
            )

    monkeypatch.setattr(workflow, "ModelClient", FakeModel)
    cfg = ExperimentConfig(
        "offline", "2023-07-01", "2023-10-31", "2024-01-31", "2024-06-30", rounds=2, count=1
    )
    ctx = Context(store)
    result = mine(asdict(cfg), ctx)
    assert result["accepted"] >= 1 and len(prompts) == 2
    resumed = mine(asdict(cfg), ctx)
    assert resumed == result and len(prompts) == 2  # 恢复不重复请求，也不把人工基线计入模型有效数。
    assert cfg.test_end not in "".join(prompts)
    assert all(
        e["kind"] == "development" and set(e["segments"]) == {"train", "valid"}
        for e in store.list("experiments")
    )
    factor = next(x for x in store.list("factors") if x["round"] > 0 and x["status"] == "accepted")
    parent = store.get("experiments", factor["experiment"])
    daily = store.read(parent["segments"]["valid"]["daily"])
    changed = asdict(cfg.backtest)
    changed["fee"] *= 2
    new = execute("retest", {"experiment": factor["experiment"], "backtest": changed}, ctx)
    pd.testing.assert_frame_equal(daily, store.read(parent["segments"]["valid"]["daily"]))
    assert (
        store.get("experiments", new["experiment"])["config"]["backtest"]["fee"] == changed["fee"]
    )
    tested = execute("final_test", {"experiment": factor["experiment"]}, ctx)
    assert set(store.get("experiments", tested["experiment"])["segments"]) == {"test"}
    assert store.list("test_access")
    assert export_experiment(store, new["experiment"])[:2] == b"PK"


def test_duplicate_cancel_resume_and_single_executor(tmp_path, monkeypatch):
    import alphagpt.research.workflow as workflow

    store = Store(tmp_path)
    gate = threading.Event()

    def slow(kind, params, ctx):
        while not gate.wait(0.01):
            ctx.check()
        return {"ok": True}

    monkeypatch.setattr(workflow, "execute", slow)
    manager = Manager(store)
    try:
        task = manager.submit("offline", {"same": True})
        assert manager.submit("offline", {"same": True}) == task
        with pytest.raises(RuntimeError, match="执行器"):
            Manager(store)
        manager.stop(task)
        for _ in range(100):
            if store.task(task)["status"] == "stopped":
                break
            time.sleep(0.01)
        assert store.task(task)["status"] == "stopped"
        gate.set()
        assert manager.submit("offline", {"same": True}, resume=task) == task
        for _ in range(100):
            if store.task(task)["status"] == "succeeded":
                break
            time.sleep(0.01)
        assert store.task(task)["status"] == "succeeded"
    finally:
        gate.set()
        manager.close()
