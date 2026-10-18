"""把三个原有业务包串联；实验和最终测试分别持久化，禁止测试反馈进入生成。"""

from dataclasses import asdict
import hashlib
import json
import subprocess
import zipfile
import io
import numpy as np
import pandas as pd
from alphagpt.api.models import ModelClient, generation_prompt, parse_candidates
from alphagpt.data.futures import FuturesData, TushareSource, load_snapshot
from alphagpt.factor.research import (
    features,
    expression,
    validate_candidate,
    FEATURES,
    BASELINES,
    formula_explanation,
)
from alphagpt.backtest.futures import backtest, executable_labels
from .config import DownloadConfig, ExperimentConfig, ModelProfile, BacktestConfig, ROOT
from .jobs import Context
from .storage import Store, identifier, now, dumps


def version_info() -> dict:
    try:
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except subprocess.SubprocessError:
        revision = "unknown"
    digest = hashlib.sha256()
    for path in sorted((ROOT / "src").rglob("*.py")):
        digest.update(str(path.relative_to(ROOT)).encode() + path.read_bytes())
    return {"git_head": revision, "source_sha256": digest.hexdigest()}


def ic_stats(values: pd.Series, labels: pd.Series) -> dict:
    aligned = pd.concat([values.rename("factor"), labels.rename("label")], axis=1).dropna()
    if len(aligned) < 20 or aligned.factor.std() <= 1e-12 or aligned.label.std() <= 1e-12:
        return {
            "ic": None,
            "rank_ic": None,
            "ic_samples": len(aligned),
            "ic_note": "样本不足或近常数",
        }
    return {
        "ic": aligned.factor.corr(aligned.label),
        "rank_ic": aligned.factor.corr(aligned.label, method="spearman"),
        "ic_samples": len(aligned),
    }


def evaluate(
    store: Store, cfg: ExperimentConfig, factor: dict, ctx: Context, test_only=False, parent=None
) -> str:
    data = load_snapshot(store, cfg.snapshot)
    f, _ = features(data)
    values, _ = expression(factor["expression"], f)
    labels = executable_labels(data, cfg.backtest.decision_lag)
    experiment_id = identifier("test" if test_only else "eval")
    base = f"experiments/{experiment_id}"
    windows = (
        {
            "test": (
                (pd.Timestamp(cfg.valid_end) + pd.Timedelta(days=1)).date().isoformat(),
                cfg.test_end,
            )
        }
        if test_only
        else {
            "train": (cfg.train_start, cfg.train_end),
            "valid": (
                (pd.Timestamp(cfg.train_end) + pd.Timedelta(days=1)).date().isoformat(),
                cfg.valid_end,
            ),
        }
    )
    result = {
        "factor_id": factor["id"],
        "factor": factor,
        "snapshot": cfg.snapshot,
        "config": asdict(cfg),
        "created": now(),
        "task": ctx.id,
        "version": version_info(),
        "segments": {},
        "parent_experiment": parent,
        "kind": "test" if test_only else "development",
    }
    # 因子值是因果的，但开发实验的文件也只保存开发区，避免导出时暴露测试标签。
    cutoff = cfg.test_end if test_only else cfg.valid_end
    store.frame(f"{base}/factor.parquet", values.loc[:cutoff].rename("factor").reset_index())
    for segment, (start, end) in windows.items():
        ctx.check()
        daily, trades, m = backtest(
            data, values, cfg.backtest, start, end, factor.get("expected_direction", 1)
        )
        if len(daily) < 20:
            raise ValueError(f"{segment} 至少需要20个交易日，当前 {len(daily)}")
        # 标签在分段末端必须截断，不能拿验证/测试未来价格补训练最后几天的标签。
        safe_labels = labels.copy()
        dates = list(labels.index)
        for pos, day in enumerate(dates):
            if (
                pos + cfg.backtest.decision_lag + 1 >= len(dates)
                or dates[pos + cfg.backtest.decision_lag + 1] > end
            ):
                safe_labels.loc[day] = np.nan
        m.update(ic_stats(values.loc[start:end], safe_labels.loc[start:end]))
        dp = store.frame(f"{base}/{segment}_daily.parquet", daily)
        tp = store.frame(f"{base}/{segment}_trades.parquet", trades)
        label_path = store.frame(
            f"{base}/{segment}_labels.parquet",
            safe_labels.loc[start:end].rename("label").reset_index(),
        )
        result["segments"][segment] = {
            "start": start,
            "end": end,
            "metrics": m,
            "daily": dp,
            "trades": tp,
            "labels": label_path,
        }
        ctx.log(
            "backtest_segment",
            experiment=experiment_id,
            factor=factor["name_zh"],
            segment=segment,
            metrics=m,
        )
    store.put("experiments", experiment_id, result)
    (store.root / base / "manifest.json").write_text(dumps(result), encoding="utf-8")
    return experiment_id


def mine(params: dict, ctx: Context) -> dict:
    cfg = ExperimentConfig.from_dict(params)
    cfg.validate()
    store = ctx.store
    snapshot = store.get("snapshots", cfg.snapshot)
    if not snapshot or cfg.train_start < snapshot["start"] or cfg.test_end > snapshot["end"]:
        raise ValueError("研究日期须在数据快照的可研究范围内")
    data = load_snapshot(store, cfg.snapshot)
    f, _ = features(data)
    development = f.loc[cfg.train_start : cfg.valid_end]
    usable = [
        name
        for name in development
        if development[name].notna().mean() >= 0.8 and development[name].std() > 1e-8
    ]
    if len(development) < 80 or len(usable) < 10:
        raise ValueError("开发区有效特征覆盖不足，需增加数据预热或研究区间")
    ctx.log(
        "feature_quality",
        available=usable,
        excluded=[name for name in development if name not in usable],
        coverage=development.notna().mean().to_dict(),
    )
    development = development[usable]
    store.put(
        "runs",
        ctx.id,
        {"config": params, "snapshot": cfg.snapshot, "created": now(), "version": version_info()},
    )
    accepted, feedback, canonical = [], [], set()
    existing = [
        x for x in store.list("factors") if x.get("task") == ctx.id and x.get("round", 0) > 0
    ]
    for obj in existing:
        feedback.append(
            {
                k: obj[k]
                for k in ["id", "expression", "status", "reason", "valid_metrics"]
                if k in obj
            }
        )
        if obj.get("canonical"):
            canonical.add(obj["canonical"])
        if obj["status"] == "accepted":
            accepted.append((obj["id"], expression(obj["expression"], development)[0]))
    # 人工基线也使用同一套真实月合约账本，并明确来源。
    for j, baseline in enumerate(BASELINES):
        key = f"{ctx.id}_baseline_{j}"
        if not store.get("factors", key):
            obj = {
                **baseline,
                "id": key,
                "task": ctx.id,
                "round": 0,
                "source": "人工基线",
                "status": "accepted",
            }
            experiment_id = evaluate(store, cfg, obj, ctx)
            obj["experiment"] = experiment_id
            store.put("factors", key, obj)
    client = ModelClient(cfg.model, ctx)
    for round_no in range(1, cfg.rounds + 1):
        ctx.check()
        key = f"{ctx.id}_{round_no}"
        round_obj = store.get("rounds", key)
        if not round_obj:
            prompt = generation_prompt(
                cfg.count, cfg.direction, {name: FEATURES[name] for name in usable}, feedback
            )
            for repair in range(3):
                content = client.call(prompt, cfg.max_calls, cfg.token_budget)
                try:
                    candidates = parse_candidates(content)
                    if not candidates:
                        raise ValueError("候选数组为空")
                    break
                except (ValueError, TypeError) as e:
                    ctx.log("json_repair", error=str(e), round=round_no, attempt=repair + 1)
                    if repair == 2:
                        raise
                    prompt += "\n上次响应无法解析，请纠正JSON，不增加说明文字。错误：" + str(e)
            round_obj = {
                "candidates": candidates[: cfg.count],
                "feedback_at_request": feedback.copy(),
                "round": round_no,
            }
            store.put("rounds", key, round_obj)
        for j, raw in enumerate(round_obj["candidates"]):
            ctx.check()
            fid = f"{ctx.id}_r{round_no}_{j}"
            if store.get("factors", fid):
                continue
            obj = {
                "id": fid,
                "task": ctx.id,
                "round": round_no,
                "source": cfg.model.provider,
                "model": cfg.model.model,
                "status": "rejected",
                "raw": raw,
            }
            try:
                obj.update(validate_candidate(raw))
                v, ast_key = expression(obj["expression"], development)
                obj["canonical"] = ast_key
                if ast_key in canonical:
                    raise ValueError("表达式重复")
                canonical.add(ast_key)
                if v.notna().mean() < 0.8 or v.dropna().std() < 1e-8:
                    raise ValueError("近常数或有效覆盖不足80%")
                for previous_id, previous in accepted:
                    corr = v.corr(previous)
                    if pd.notna(corr) and abs(corr) >= cfg.correlation_limit:
                        raise ValueError(f"与 {previous_id} 开发区相关性 {corr:.4f} 超限")
                obj["status"] = "accepted"
                eid = evaluate(store, cfg, obj, ctx)
                obj["experiment"] = eid
                obj["valid_metrics"] = store.get("experiments", eid)["segments"]["valid"]["metrics"]
                accepted.append((fid, v))
            except (ValueError, SyntaxError, TypeError, ZeroDivisionError) as e:
                obj["status"], obj["reason"] = "rejected", str(e)
            store.put("factors", fid, obj)
            feedback.append(
                {
                    k: obj[k]
                    for k in ["id", "expression", "status", "reason", "valid_metrics"]
                    if k in obj
                }
            )
            ctx.progress(
                "因子评估",
                round=round_no,
                completed=j + 1,
                total=len(round_obj["candidates"]),
                accepted=len(accepted),
                factor=obj.get("name_zh", fid),
            )
            ctx.log("factor_result", factor=obj)
    if not accepted:
        raise ValueError("模型候选全部被淘汰；原始响应和失败原因已保存，人工基线仍可查看")
    return {
        "run": ctx.id,
        "accepted": len(accepted),
        "attempted": len(
            [x for x in store.list("factors") if x.get("task") == ctx.id and x.get("round", 0) > 0]
        ),
    }


def execute(kind: str, params: dict, ctx: Context) -> dict:
    if kind == "sync":
        return FuturesData(ctx.store, TushareSource(DownloadConfig(**params), ctx)).sync()
    if kind == "mine":
        return mine(params, ctx)
    if kind == "connection":
        model = ModelProfile(**params)
        return {
            "response": ModelClient(model, ctx).call(
                '仅返回 JSON 对象 {"status":"连接成功"}，不添加其他说明。',
                max_calls=1,
                token_budget=20000,
            )
        }
    if kind in ("retest", "final_test"):
        parent = ctx.store.get("experiments", params["experiment"])
        if not parent:
            raise ValueError("原实验不存在")
        cfg = ExperimentConfig.from_dict(parent["config"])
        if "backtest" in params:
            cfg.backtest = BacktestConfig(**params["backtest"])
        if kind == "final_test":
            ctx.store.put(
                "test_access",
                ctx.id,
                {
                    "parent": params["experiment"],
                    "factor": parent["factor_id"],
                    "config": asdict(cfg),
                    "viewed_at": now(),
                    "note": "本版本测试已解封，不得用其反馈宣称新的独立测试",
                },
            )
        eid = evaluate(
            ctx.store,
            cfg,
            parent["factor"],
            ctx,
            test_only=kind == "final_test",
            parent=params["experiment"],
        )
        return {"experiment": eid}
    raise ValueError("未知任务类别")


def export_experiment(store: Store, key: str) -> bytes:
    obj = store.get("experiments", key)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", dumps(obj))
        z.writestr(
            "因子逻辑.md",
            "# "
            + obj["factor"]["name_zh"]
            + "\n\n"
            + obj["factor"]["expression"]
            + "\n\n"
            + obj["factor"]["logic_zh"],
        )
        z.writestr("公式计算释义.md", formula_explanation(obj["factor"]["expression"]))
        for segment, entry in obj["segments"].items():
            for name in ("daily", "trades", "labels"):
                z.writestr(f"{segment}_{name}.csv", store.read(entry[name]).to_csv(index=False))
        z.writestr("task_log.jsonl", (store.root / "logs" / (obj["task"] + ".jsonl")).read_text())
    return buffer.getvalue()
