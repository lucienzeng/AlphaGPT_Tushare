"""薄 UI：只提交冻结参数，业务计算由原项目包承担。"""

from dataclasses import asdict
from datetime import date, timedelta
import json
import os
import pandas as pd
import plotly.express as px
import streamlit as st
from alphagpt.research.config import (
    load_credentials,
    DownloadConfig,
    ExperimentConfig,
    ModelProfile,
    BacktestConfig,
    profiles,
    ROOT,
)
from alphagpt.research.storage import Store, dumps
from alphagpt.research.jobs import Manager
from alphagpt.research.workflow import export_experiment
from alphagpt.data.futures import ROW_LIMITS
from alphagpt.data.sqlite import MarketData
from alphagpt.factor.research import formula_explanation

st.set_page_config(page_title="沪铜因子研究台", page_icon="📈", layout="wide")


@st.cache_resource
def resources():
    load_credentials()
    store = Store()
    manager = Manager(store)
    try:
        MarketData(store).migrate_legacy()
    except Exception:
        manager.close()
        raise
    return store, manager


store, manager = resources()
st.title("沪铜因子研究台")
st.caption("Tushare 真实数据 · 中文因子逻辑 · 真实月合约回测 · 本地持久化日志")
page = st.sidebar.radio("工作区", ["数据同步", "因子挖掘", "回测结果"])
st.sidebar.caption("凭据状态（不显示密钥）")
for name in ("TUSHARE_TOKEN", "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "MOONSHOT_API_KEY"):
    st.sidebar.write(("✓ " if os.getenv(name) else "○ ") + name)
st.sidebar.caption("原始行情：runtime/research.sqlite；快照：runtime/snapshots")


def submit(kind, params):
    try:
        key = manager.submit(kind, params)
        st.session_state["task"] = key
        st.session_state["task_selection"] = key
        st.success("已提交任务：" + key)
    except Exception as e:
        st.error(str(e))


@st.fragment(run_every=2)
def task_panel():
    tasks = store.tasks()
    if not tasks:
        st.info("暂无任务。下载与模型请求只在点击开始后执行。")
        return
    keys = [t["id"] for t in tasks]
    selected = st.selectbox(
        "任务记录",
        keys,
        index=keys.index(st.session_state["task"]) if st.session_state.get("task") in keys else 0,
        key="task_selection",
    )
    t = store.task(selected)
    labels = {
        "queued": "等待执行",
        "running": "运行中",
        "succeeded": "成功",
        "failed": "失败",
        "stopped": "已停止",
        "interrupted": "程序中断",
    }
    st.write(f"**{labels.get(t['status'], t['status'])}** · {t['payload'].get('stage', '')}")
    p = t["payload"]
    if p.get("total") and p.get("completed") is not None:
        st.progress(min(1.0, p["completed"] / p["total"]))
    if p.get("error"):
        st.error(p["error"])
    cols = st.columns(2)
    if t["status"] in ("queued", "running") and cols[0].button(
        "停止此任务", key="stop_" + selected
    ):
        manager.stop(selected)
        st.info("已请求停止，等待当前请求安全结束；不会发送新请求。")
    if t["status"] in ("failed", "stopped", "interrupted") and cols[1].button(
        "从完成边界恢复", key="resume_" + selected
    ):
        manager.submit(t["kind"], t["params"], resume=selected)
    with st.expander("任务详情与完整日志", expanded=t["status"] in ("failed", "running")):
        st.json({"参数": t["params"], "进度": p})
        rows = [
            {k: dumps(v) if isinstance(v, (dict, list)) else v for k, v in event.items()}
            for event in store.events(selected, 80)
        ]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        path = store.root / "logs" / (selected + ".jsonl")
        if path.exists():
            st.download_button(
                "下载完整运行日志",
                path.read_bytes(),
                file_name=path.name,
                mime="application/jsonl",
                key="log_" + selected,
            )


def backtest_controls(prefix="") -> BacktestConfig:
    cols = st.columns(3)
    capital = cols[0].number_input(
        "研究初始资金（元）",
        min_value=10000.0,
        value=1_000_000.0,
        step=10000.0,
        key=prefix + "capital",
    )
    exposure = cols[1].number_input(
        "名义敞口/权益", min_value=0.01, max_value=1.0, value=0.8, key=prefix + "exposure"
    )
    margin = cols[2].number_input(
        "保证金预算/权益", min_value=0.01, max_value=1.0, value=0.35, key=prefix + "margin"
    )
    cols = st.columns(3)
    mode = cols[0].selectbox(
        "手续费模式", ["单边成交额费率", "单边元/手", "历史参数"], key=prefix + "fee_mode"
    )
    fee = cols[1].number_input(
        "单边费率小数或元/手",
        min_value=0.0,
        value=0.00005,
        step=0.00001,
        format="%.6f",
        key=prefix + "fee",
    )
    slip = cols[2].number_input(
        "单边滑点（tick）", min_value=0.0, value=1.0, step=0.5, key=prefix + "slippage"
    )
    with st.expander("信号与成交高级参数"):
        c = st.columns(3)
        window = c[0].number_input(
            "标准化窗口（交易日）", min_value=10, value=60, key=prefix + "window"
        )
        threshold = c[1].number_input(
            "信号阈值", min_value=0.0, value=0.5, key=prefix + "threshold"
        )
        lag = c[2].number_input(
            "决策到执行延迟（交易日）", min_value=1, value=2, key=prefix + "lag"
        )
        c = st.columns(3)
        tick = c[0].number_input(
            "最小价位（元/吨）", min_value=0.01, value=10.0, key=prefix + "tick"
        )
        broker = c[1].number_input(
            "期货公司加收（单边元/手）", min_value=0.0, value=0.0, key=prefix + "broker"
        )
        buffer = c[2].number_input(
            "到期前退出缓冲（日历天）", min_value=1, value=10, key=prefix + "buffer"
        )
    return BacktestConfig(
        capital=capital,
        exposure=exposure,
        margin_cap=margin,
        fee_mode={"单边成交额费率": "rate", "单边元/手": "per_lot", "历史参数": "historical"}[mode],
        fee=fee,
        slippage_ticks=slip,
        signal_window=window,
        threshold=threshold,
        decision_lag=lag,
        tick_size=tick,
        broker_fee_per_lot=broker,
        delivery_buffer_days=buffer,
    )


if page == "数据同步":
    st.subheader("数据覆盖与下载")
    market = MarketData(store)
    st.info(
        "原始数据统一存储在 SQLite。DBeaver 选择 SQLite，连接下方文件即可浏览业务表及中文视图。"
    )
    st.code(str(store.root / "research.sqlite"), language="text")
    with st.expander("下载缺口记录（含待补充与已补齐）", expanded=True):
        with store.connect() as db:
            gap_records = pd.read_sql_query(
                'SELECT * FROM "期货_下载缺口记录" ORDER BY 状态,缺失日期 DESC,合约代码', db
            )
        if gap_records.empty:
            st.caption("暂无下载缺口记录。")
        else:
            st.warning(f"待补充 {int(gap_records.状态.eq('open').sum())} 条；结算参数缺失不会中断同步，历史手续费回测仍严格检查。")
            st.dataframe(gap_records, hide_index=True, width="stretch")
            st.caption("open=待补充；resolved=已补齐。普通同步仍会重试缺失日期，补齐后自动更新状态。")
    with st.expander("数据库业务表与覆盖（DBeaver 同源）", expanded=True):
        coverage = market.summary()
        if coverage.empty:
            st.caption("数据库暂无原始行情，请先同步数据。")
        else:
            summary = coverage.groupby(["数据接口", "数据类别"], as_index=False).agg(
                合约或交易所数量=("合约或交易所", "nunique"),
                行数=("行数", "sum"),
                起始日期=("起始日期", "min"),
                结束日期=("结束日期", "max"),
            )
            st.dataframe(summary, hide_index=True, width="stretch")
            with st.expander("各合约覆盖明细"):
                st.dataframe(coverage, hide_index=True, width="stretch")
            st.caption(
                "这里展示全部已入库分段，含历史未完成任务的数据；研究请使用下方成功的数据快照。"
            )
            with st.expander("主连映射与关联数据缺口"):
                with store.connect() as db:
                    gaps = pd.read_sql_query(
                        'SELECT * FROM "期货_数据缺口" ORDER BY 交易日,合约代码', db
                    )
                    links = pd.read_sql_query(
                        'SELECT * FROM "沪铜_主力映射" ORDER BY 交易日 DESC LIMIT 100', db
                    )
                st.write(
                    f"当前已入库数据的关联缺口：{len(gaps)} 条；按接口分别计数，不等于缺失交易日数。"
                )
                st.dataframe(gaps, hide_index=True, width="stretch")
                st.caption("最近100条主力映射；数据库内可浏览全部记录。")
                st.dataframe(links, hide_index=True, width="stretch")
        if st.checkbox("浏览 SQLite 月份合约原始行情"):
            codes = (
                coverage.loc[coverage.数据接口.eq("fut_daily"), "合约或交易所"].tolist()
                if not coverage.empty
                else []
            )
            if codes:
                raw_code = st.selectbox("数据库月合约", sorted(codes))
                st.dataframe(market.read("fut_daily", raw_code), hide_index=True, width="stretch")
    snapshots = store.list("snapshots")
    if snapshots:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        k: s.get(k)
                        for k in ["id", "start", "end", "rows", "contracts", "created", "source"]
                    }
                    for s in snapshots
                ]
            ),
            hide_index=True,
            width="stretch",
        )
        latest = snapshots[0]
        with st.expander("各类数据覆盖与质量"):
            records = []
            for kind, path in latest["paths"].items():
                frame = store.read(path)
                col = "trade_date" if "trade_date" in frame else "cal_date"
                records.append(
                    {
                        "类别": kind,
                        "行数": len(frame),
                        "起始": frame[col].min() if col in frame else None,
                        "结束": frame[col].max() if col in frame else None,
                    }
                )
            st.dataframe(pd.DataFrame(records), hide_index=True, width="stretch")
            st.json(latest.get("quality", {}))
    else:
        st.info("还没有真实数据快照。请选择历史区间开始同步。")
    with st.form("sync_form"):
        cols = st.columns(2)
        start = cols[0].date_input(
            "下载开始日期",
            value=date.fromisoformat(snapshots[0]["start"]) if snapshots else date(2024, 1, 1),
        )
        end = cols[1].date_input(
            "下载结束日期",
            value=date.fromisoformat(snapshots[0]["end"]) if snapshots else date(2024, 12, 31),
            max_value=date.today() - timedelta(days=1),
        )
        cols = st.columns(3)
        rpm = cols[0].number_input("账号预算（次/分钟）", min_value=1, max_value=500, value=30)
        timeout = cols[1].number_input("请求超时（秒）", min_value=5, max_value=120, value=30)
        retry = cols[2].number_input("最大重试次数", min_value=0, max_value=5, value=3)
        with st.expander("同步高级设置与行数限制"):
            warmup = st.number_input("额外预热（日历天）", min_value=120, max_value=1000, value=250)
            endpoint_json = st.text_area("各接口频次 JSON（取账号与接口较小值）", value="{}")
            row_json = st.text_area("各接口单次行数 JSON（只能收紧已知上限）", value="{}")
            tail_days = st.number_input(
                "自动尾部复查范围（条交易日，0关闭）", min_value=0, max_value=30, value=0
            )
            tail_hours = st.number_input(
                "尾部复查最短间隔（小时）", min_value=1, max_value=720, value=24
            )
            repair = st.checkbox("修复选定区间：允许重拉该区间和预热数据", value=False)
            st.json(ROW_LIMITS)
        st.caption(
            "默认并发1、平滑30次/分是研发保守配置，不代表账号官方权限；实际按更严格限制设置。正常同步仅补缺口，修复不覆盖旧快照。"
        )
        if st.form_submit_button("开始下载 / 增量同步", type="primary"):
            try:
                cfg = DownloadConfig(
                    start.isoformat(),
                    end.isoformat(),
                    rpm=int(rpm),
                    timeout=int(timeout),
                    retries=int(retry),
                    warmup_days=int(warmup),
                    repair=repair,
                    endpoint_rpm=json.loads(endpoint_json),
                    row_limits=json.loads(row_json),
                    tail_days=int(tail_days),
                    tail_check_hours=int(tail_hours),
                )
                cfg.validate()
                submit("sync", asdict(cfg))
            except Exception as e:
                st.error(str(e))
    task_panel()
    if snapshots:
        with st.expander("真实数据预览与价格"):
            chosen = st.selectbox("预览快照", [s["id"] for s in snapshots])
            bars = store.read(store.get("snapshots", chosen)["paths"]["bars"])
            symbol = st.selectbox("月合约", sorted(bars.ts_code.unique()))
            sample = bars[bars.ts_code.eq(symbol)].sort_values("trade_date")
            st.plotly_chart(
                px.line(
                    sample, x="trade_date", y=["close", "settle"], title=symbol + " 实际合约价格"
                ),
                width="stretch",
            )
            st.dataframe(sample.tail(100), width="stretch", hide_index=True)

elif page == "因子挖掘":
    st.subheader("模型配置与因子挖掘")
    options = profiles()
    name = st.selectbox("模型供应商配置", list(options))
    profile = options[name]
    cols = st.columns(2)
    model = cols[0].text_input("模型 ID", value=profile.model, key=name + "_model")
    base_url = cols[1].text_input("Base URL", value=profile.base_url, key=name + "_url")
    with st.expander("模型高级参数"):
        key_env = st.text_input("密钥环境变量名", value=profile.key_env, key=name + "_env")
        protocol = st.selectbox(
            "API 协议",
            ["chat", "responses"],
            index=0 if profile.protocol == "chat" else 1,
            key=name + "_protocol",
        )
        output = st.number_input(
            "单次输出 Token 上限", min_value=128, max_value=16000, value=profile.max_tokens
        )
        model_timeout = st.number_input(
            "模型超时（秒）",
            min_value=10,
            max_value=600,
            value=profile.timeout,
            key=name + "_timeout",
        )
        optional = st.text_area(
            "供应商可选参数 JSON", value=dumps(profile.optional_params), key=name + "_params"
        )
    try:
        selected_model = ModelProfile(
            profile.provider,
            model,
            base_url,
            key_env,
            protocol,
            int(model_timeout),
            int(output),
            json.loads(optional),
        )
    except ValueError as e:
        st.error("模型参数 JSON 无效：" + str(e))
        st.stop()
    c = st.columns(2)
    if c[0].button("测试模型连接"):
        submit("connection", asdict(selected_model))
    if c[1].button("保存此模型配置"):
        cfg_path = ROOT / "models.json"
        saved = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
        saved[name] = asdict(selected_model)
        cfg_path.write_text(dumps(saved), encoding="utf-8")
        st.success("已保存非敏感模型配置；密钥仍从环境变量读取")
    snapshots = store.list("snapshots")
    if not snapshots:
        st.info("请先在数据同步页面建立真实数据快照。")
    else:
        snapshot_id = st.selectbox("研究数据快照", [s["id"] for s in snapshots])
        snap = store.get("snapshots", snapshot_id)
        viewed = [x for x in store.list("test_access") if x["config"]["snapshot"] == snapshot_id]
        if viewed:
            st.warning(
                f"此快照已有 {len(viewed)} 次测试区解封记录。若沿用已查看的区间继续调参，应按开发数据看待。"
            )
        start, end = date.fromisoformat(snap["start"]), date.fromisoformat(snap["end"])
        span = (end - start).days
        with st.form("mine_form"):
            cols = st.columns(4)
            ts = cols[0].date_input("训练开始", value=start, min_value=start, max_value=end)
            te = cols[1].date_input(
                "训练结束",
                value=start + timedelta(days=int(span * 0.6)),
                min_value=start,
                max_value=end,
            )
            ve = cols[2].date_input(
                "验证结束",
                value=start + timedelta(days=int(span * 0.8)),
                min_value=start,
                max_value=end,
            )
            xe = cols[3].date_input("测试结束", value=end, min_value=start, max_value=end)
            cols = st.columns(4)
            rounds = cols[0].number_input("挖掘轮数", min_value=1, max_value=20, value=1)
            count = cols[1].number_input("每轮因子数", min_value=1, max_value=50, value=10)
            calls = cols[2].number_input("模型调用总上限", min_value=1, max_value=100, value=6)
            tokens = cols[3].number_input(
                "任务 Token 预算", min_value=1000, max_value=2000000, value=50000, step=1000
            )
            direction = st.text_area(
                "研究方向",
                value="探索沪铜趋势、反转与量价持仓交互；每个公式必须附中文逻辑及失效条件。",
            )
            bt = backtest_controls("mine_")
            st.caption(
                f"最多候选 {rounds * count} 个；快照 {snap['start']} ～ {snap['end']}。测试集默认封存，不参与生成反馈。默认成交额费率是可编辑的研究假设，并非实际账户报价。"
            )
            if st.form_submit_button("开始因子挖掘", type="primary"):
                try:
                    if not os.getenv(key_env):
                        raise ValueError(f"尚未配置 {key_env}")
                    cfg = ExperimentConfig(
                        snapshot_id,
                        ts.isoformat(),
                        te.isoformat(),
                        ve.isoformat(),
                        xe.isoformat(),
                        int(rounds),
                        int(count),
                        direction,
                        int(calls),
                        int(tokens),
                        model=selected_model,
                        backtest=bt,
                    )
                    cfg.validate()
                    submit("mine", asdict(cfg))
                except Exception as e:
                    st.error(str(e))
    task_panel()

else:
    st.subheader("因子与回测结果")
    factors = store.list("factors")
    if not factors:
        st.info("尚无因子。请先下载数据并启动挖掘。")
    else:
        table = []
        for f in factors:
            m = f.get("valid_metrics", {})
            if not m and f.get("experiment"):
                m = (
                    store.get("experiments", f["experiment"])["segments"]
                    .get("valid", {})
                    .get("metrics", {})
                )
            table.append(
                {
                    "因子ID": f["id"],
                    "名称": f.get("name_zh", "无效候选"),
                    "轮次": f["round"],
                    "来源": f["source"],
                    "状态": {"accepted": "有效候选", "rejected": "已淘汰"}.get(
                        f["status"], f["status"]
                    ),
                    "验证夏普": m.get("sharpe"),
                    "验证收益": m.get("total_return"),
                    "验证回撤": m.get("max_drawdown"),
                    "原因": f.get("reason", ""),
                }
            )
        listing = pd.DataFrame(table).sort_values("验证夏普", ascending=False, na_position="last")
        filters = st.columns(2)
        states = filters[0].multiselect("候选状态筛选", sorted(listing["状态"].unique()))
        sources = filters[1].multiselect("候选来源筛选", sorted(listing["来源"].unique()))
        if states:
            listing = listing[listing["状态"].isin(states)]
        if sources:
            listing = listing[listing["来源"].isin(sources)]
        if listing.empty:
            st.info("该筛选条件下没有候选")
            task_panel()
            st.stop()
        st.dataframe(listing, width="stretch", hide_index=True)
        chosen = st.selectbox(
            "查看因子",
            listing["因子ID"].tolist(),
            format_func=lambda k: store.get("factors", k).get("name_zh", k) + " · " + k[-16:],
        )
        f = store.get("factors", chosen)
        st.markdown("**中文逻辑解析**")
        st.write(f.get("logic_zh", "该候选未通过必填校验，详见淘汰原因"))
        st.code(f.get("expression", ""), language="text")
        with st.expander("公式逐项计算释义与符号约定"):
            try:
                st.markdown(formula_explanation(f.get("expression", "")))
            except SyntaxError:
                st.info("该候选公式未通过语法校验，无法解析")
        st.write(
            {
                "适用行情": f.get("market_regime"),
                "失效风险": f.get("failure_risks"),
                "预期方向": f.get("expected_direction"),
                "状态": f["status"],
                "原因": f.get("reason"),
            }
        )
        experiments = [x for x in store.list("experiments") if x["factor_id"] == chosen]
        if experiments:
            eid = st.selectbox("实验记录（不同成本独立保存）", [x["id"] for x in experiments])
            experiment = store.get("experiments", eid)
            with st.expander("冻结参数与来源"):
                st.json(experiment)
            segment = st.radio(
                "数据区间",
                list(experiment["segments"]),
                horizontal=True,
                format_func=lambda x: {"train": "训练区", "valid": "验证区", "test": "最终测试区"}[
                    x
                ],
            )
            entry = experiment["segments"][segment]
            st.write(
                f"区间：{entry['start']} ～ {entry['end']}；"
                + (
                    "本版本最终测试已解封并记录查看。"
                    if segment == "test"
                    else "此处仅显示开发区结果。"
                )
            )
            headline = st.columns(4)
            m = entry["metrics"]
            headline[0].metric("区间净收益", f"{m['total_return']:.2%}")
            headline[1].metric(
                "年化夏普", f"{m['sharpe']:.2f}" if m.get("sharpe") is not None else "不可计算"
            )
            headline[2].metric("最大回撤", f"{m['max_drawdown']:.2%}")
            headline[3].metric("费用＋滑点（元）", f"{m['fees'] + m['slippage_cost']:,.2f}")
            st.dataframe(pd.DataFrame([entry["metrics"]]), hide_index=True, width="stretch")
            daily = store.read(entry["daily"])
            daily["nav"] = (1 + daily.net_return).cumprod()
            daily["gross_nav"] = (1 + daily.gross_return).cumprod()
            daily["drawdown"] = daily.nav / daily.nav.cummax().clip(lower=1) - 1
            st.plotly_chart(
                px.line(daily, x="trade_date", y=["nav", "gross_nav"], title="成本前后净值"),
                width="stretch",
            )
            st.plotly_chart(
                px.area(daily, x="trade_date", y="drawdown", title="回撤"), width="stretch"
            )
            st.plotly_chart(
                px.line(daily, x="trade_date", y="quantity", title="真实月合约持仓（手）"),
                width="stretch",
            )
            fp = f"experiments/{eid}/factor.parquet"
            vals = store.read(fp).set_index("trade_date").factor.loc[entry["start"] : entry["end"]]
            labels = store.read(entry["labels"]).set_index("trade_date").label
            rolling = vals.rolling(40, min_periods=20).corr(labels)
            chart = pd.DataFrame({"factor": vals, "rolling_ic": rolling}).reset_index()
            st.plotly_chart(
                px.line(chart, x="trade_date", y="factor", title="因子值"), width="stretch"
            )
            st.plotly_chart(
                px.line(
                    chart, x="trade_date", y="rolling_ic", title="滚动时间序列 IC（40日 Pearson）"
                ),
                width="stretch",
            )
            daily["month"] = daily.trade_date.str[:7]
            monthly = (
                daily.groupby("month").net_return.apply(lambda x: (1 + x).prod() - 1).reset_index()
            )
            st.plotly_chart(
                px.bar(monthly, x="month", y="net_return", title="月度收益"), width="stretch"
            )
            daily["year"] = daily.trade_date.str[:4]
            st.dataframe(
                daily.groupby("year").agg(
                    年度收益=("net_return", lambda x: (1 + x).prod() - 1),
                    费用=("fee", "sum"),
                    滑点=("slippage_cost", "sum"),
                    平均换手=("turnover", "mean"),
                ),
                width="stretch",
            )
            with st.expander("成交、换月与未成交明细"):
                st.dataframe(store.read(entry["trades"]), width="stretch", hide_index=True)
                st.dataframe(daily, width="stretch", hide_index=True)
            st.download_button(
                "导出完整实验与运行日志",
                export_experiment(store, eid),
                file_name=eid + ".zip",
                mime="application/zip",
            )
            with st.expander("修改成本重新回测（不调用模型）"):
                bt_new = backtest_controls("rerun_")
                if st.button("创建新回测实验"):
                    submit("retest", {"experiment": eid, "backtest": asdict(bt_new)})
            st.warning(
                "解封最终测试后，该区间已被查看；不得把它用于后续模型反馈并继续称为独立测试。"
            )
            if experiment["kind"] == "development" and st.button("冻结此版本并运行最终测试"):
                submit("final_test", {"experiment": eid})
        accepted = [x for x in store.list("experiments") if x["kind"] == "development"]
        if accepted:
            with st.expander("比较验证区净值"):
                selection = st.multiselect(
                    "比较实验（最多5个）", [x["id"] for x in accepted], max_selections=5
                )
                lines = []
                for key in selection:
                    obj = store.get("experiments", key)
                    d = store.read(obj["segments"]["valid"]["daily"])
                    d["nav"] = (1 + d.net_return).cumprod()
                    d["实验"] = obj["factor"]["name_zh"] + " · " + key[-8:]
                    lines.append(d)
                if lines:
                    st.plotly_chart(
                        px.line(pd.concat(lines), x="trade_date", y="nav", color="实验"),
                        width="stretch",
                    )
    task_panel()
