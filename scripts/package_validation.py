"""汇总已发生的真实 UI 操作与日志，不发模型或行情请求。"""

import argparse
from pathlib import Path
import json
import zipfile
import pandas as pd
from alphagpt.research.storage import Store, dumps, now
from alphagpt.research.workflow import version_info


def main():
    p = argparse.ArgumentParser()
    for name in ("sync", "mine", "retest", "final", "connection"):
        p.add_argument("--" + name, required=True)
    args = p.parse_args()
    store = Store()
    tasks = {name: store.task(getattr(args, name)) for name in vars(args)}
    assert all(t["status"] == "succeeded" for t in tasks.values())
    assert tasks["sync"]["payload"]["result"]["requests"] == 0
    factors = [f for f in store.list("factors") if f.get("task") == args.mine]
    candidates = [f for f in factors if f.get("round", 0) > 0]
    calls = [c for c in store.list("calls") if c["task"] == args.mine]
    events = store.events(args.mine, 10000)
    assert len(candidates) == 3 and len(calls) == 1
    assert any(e["event"] == "task_stopped" for e in events)
    assert any(e["event"] == "task_submitted" and e.get("resumed") for e in events)
    parent = store.get("experiments", tasks["retest"]["params"]["experiment"])
    rerun = store.get("experiments", tasks["retest"]["payload"]["result"]["experiment"])
    final = store.get("experiments", tasks["final"]["payload"]["result"]["experiment"])
    parent["id"] = tasks["retest"]["params"]["experiment"]
    rerun["id"] = tasks["retest"]["payload"]["result"]["experiment"]
    final["id"] = tasks["final"]["payload"]["result"]["experiment"]
    assert parent["factor_id"] == rerun["factor_id"] == final["factor_id"]
    assert rerun["config"]["backtest"]["fee"] == parent["config"]["backtest"]["fee"] * 2
    assert set(final["segments"]) == {"test"}
    assert final["parent_experiment"] == rerun["id"]
    original_file = json.loads(
        (store.root / f"experiments/{parent['id']}/manifest.json").read_text()
    )
    assert original_file == {k: v for k, v in parent.items() if k != "id"}
    rolls = sum(
        store.read(v["trades"]).get("reason", pd.Series(dtype=str)).str.contains("换月").sum()
        for v in parent["segments"].values()
    )
    assert rolls > 0
    report = {
        "finished": now(),
        "status": "succeeded",
        "source": "真实 Tushare / DeepSeek / 浏览器操作",
        "version": version_info(),
        "tasks": tasks,
        "checks": {
            "重复同步零请求": True,
            "界面停止并复用响应恢复": True,
            "模型请求数": len(calls),
            "模型候选数": len(candidates),
            "人工基线数": len(factors) - len(candidates),
            "原实验清单未覆盖": True,
            "成本重算费率加倍": True,
            "真实换月成交记录数": int(rolls),
            "独立测试解封记录": True,
        },
        "snapshot": store.get("snapshots", parent["snapshot"]),
        "factors": candidates,
        "model_usage": [
            {
                "requested": c["profile"]["model"],
                "actual": c["actual_model"],
                "tokens": c["total_tokens"],
                "status": c["status"],
            }
            for c in calls
        ],
        "sample": {
            "development": parent["id"],
            "retest": rerun["id"],
            "test": final["id"],
            "validation_metrics": rerun["segments"]["valid"]["metrics"],
            "test_metrics": final["segments"]["test"]["metrics"],
        },
        "notes": [
            "本报告为 UI 验收汇总，未再次调用外部 API。",
            "早期 CLI 验收与失败日志全部保留；示例不构成策略有效性证明。",
            "恢复前旧代码曾把两个人工基线计入 accepted 汇总；候选记录始终为3个，该计数已修正并有回归验证。",
            "模型中文经济解释需要人工审查；界面和导出附按实际公式生成的计算释义。",
        ],
    }
    directory = store.root / "verification"
    path = directory / "ui_acceptance.json"
    path.write_text(dumps(report), encoding="utf-8")
    experiment_ids = {f["experiment"] for f in factors if f.get("experiment")} | {
        rerun["id"],
        final["id"],
    }
    with zipfile.ZipFile(directory / "完整运行日志与验收.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for folder in ("logs", "verification"):
            for file in (store.root / folder).rglob("*"):
                if file.is_file() and file.suffix != ".zip":
                    z.write(file, str(file.relative_to(store.root)))
        for eid in experiment_ids:
            for file in (store.root / "experiments" / eid).rglob("*"):
                if file.is_file():
                    z.write(file, str(file.relative_to(store.root)))
        for file in (Path("README.md"), Path("docs/VALIDATION.md"), Path("docs/接口约定.md")):
            if file.exists():
                z.write(file, str(file))
        z.writestr("因子记录.json", dumps(factors))
    print(dumps({"report": str(path), "checks": report["checks"], "sample": report["sample"]}))


if __name__ == "__main__":
    main()
