"""因果特征、白名单 AST 与带中文逻辑的结构化候选。"""

import ast
import operator
import re
import numpy as np
import pandas as pd

FEATURES = {
    "ret5": "连续价格5日收益",
    "ret20": "连续价格20日收益",
    "ret60": "连续价格60日收益",
    "trend20": "收盘价相对20日均线偏离",
    "trend60": "收盘价相对60日均线偏离",
    "reversal": "负的3日收益，较高表示近期下跌",
    "volatility": "20日收益标准差",
    "volatility_ratio": "5日/20日收益波动率比减1",
    "range20": "20日平均日内振幅比例",
    "close_position": "收盘在当日高低区间的位置减0.5",
    "volume_ratio": "当前月合约成交量/该合约过去20日均量减1",
    "oi_change5": "当前月合约5日持仓变化率，不代表单向资金流入",
    "oi_ratio": "当前月合约持仓量/该合约过去20日均量减1",
    "volume_oi": "当前月合约成交/持仓比",
    "price_volume": "1日连续收益乘成交量偏离",
    "price_oi": "5日连续收益乘5日持仓变化率",
    "breakout": "收盘相对过去20日最高价与最低价中点偏离",
    "vol_change": "20日波动率的5日变化",
}


def features(data: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    bars = data["bars"].sort_values(["ts_code", "trade_date"]).copy()
    # 相对量与持仓变化先在真实合约内计算，避免把主力迁移误当作交易行为。
    for _, group in bars.groupby("ts_code", sort=False):
        ix = group.index
        period = group.trade_date.ge("2020-01-01").astype(int)
        for _, stable in group.groupby(period):
            index = stable.index
            bars.loc[index, "volume_ratio"] = (
                stable.vol / stable.vol.rolling(20, min_periods=10).mean().shift(1) - 1
            )
            bars.loc[index, "oi_ratio"] = (
                stable.oi / stable.oi.rolling(20, min_periods=10).mean().shift(1) - 1
            )
            bars.loc[index, "oi_change5"] = stable.oi.pct_change(5, fill_method=None)
        bars.loc[ix, "volume_oi"] = group.vol / group.oi.replace(0, np.nan)
    panel = data["mapping"].merge(
        bars,
        left_on=["trade_date", "mapping_ts_code"],
        right_on=["trade_date", "ts_code"],
        how="left",
        validate="one_to_one",
        suffixes=("_continuous", ""),
    )
    panel = panel.sort_values("trade_date").reset_index(drop=True)
    if panel.close.isna().any():
        raise ValueError("信号序列缺少主力真实行情")
    price_index = bars.set_index(["trade_date", "ts_code"])
    adjustment, prior = 1.0, None
    adjusted = []
    for row in panel.itertuples():
        if prior and prior.mapping_ts_code != row.mapping_ts_code:
            try:
                old = price_index.loc[(prior.trade_date, prior.mapping_ts_code), "close"]
                new = price_index.loc[(prior.trade_date, row.mapping_ts_code), "close"]
            except KeyError as e:
                raise ValueError("换月缺少前一交易日新旧合约价格，不能制造复权值") from e
            # 只在切换时累计当时已经知道的比例，追加未来数据不重写历史信号。
            adjustment *= old / new
        adjusted.append(adjustment)
        prior = row
    panel["adjustment"] = adjusted
    for column in ["open", "high", "low", "close"]:
        panel["signal_" + column] = panel[column] * panel.adjustment
    p = panel.signal_close
    r = p.pct_change(fill_method=None)
    f = pd.DataFrame(index=pd.Index(panel.trade_date, name="trade_date"))
    values = {
        "ret5": p.pct_change(5),
        "ret20": p.pct_change(20),
        "ret60": p.pct_change(60),
        "trend20": p / p.rolling(20).mean() - 1,
        "trend60": p / p.rolling(60).mean() - 1,
        "reversal": -p.pct_change(3),
        "volatility": r.rolling(20).std(),
        "volatility_ratio": r.rolling(5).std() / r.rolling(20).std() - 1,
        "range20": ((panel.high - panel.low) / panel.close).rolling(20).mean(),
        "close_position": (panel.close - panel.low) / (panel.high - panel.low).replace(0, np.nan)
        - 0.5,
        "volume_ratio": panel.volume_ratio,
        "oi_change5": panel.oi_change5,
        "oi_ratio": panel.oi_ratio,
        "volume_oi": panel.volume_oi,
        "price_volume": r * panel.volume_ratio,
        "price_oi": p.pct_change(5) * panel.oi_change5,
        "breakout": p
        / (
            (
                panel.signal_high.rolling(20).max().shift(1)
                + panel.signal_low.rolling(20).min().shift(1)
            )
            / 2
        )
        - 1,
        "vol_change": r.rolling(20).std().diff(5),
    }
    for name, series in values.items():
        # 严格历史统计；保留 warmup NaN，不能用 0 填充制造有效样本。
        z = (series - series.rolling(60, min_periods=30).mean().shift(1)) / series.rolling(
            60, min_periods=30
        ).std().shift(1).replace(0, np.nan)
        f[name] = z.replace([np.inf, -np.inf], np.nan).to_numpy()
    return f, panel


BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: lambda a, b: (
        a / pd.Series(b).replace(0, np.nan)
        if isinstance(b, pd.Series)
        else a / (b if abs(b) > 1e-12 else np.nan)
    ),
}
FUNCS = {
    "abs": np.abs,
    "tanh": np.tanh,
    "sqrt_abs": lambda x: np.sqrt(np.abs(x)),
    "sign": np.sign,
    "minimum": np.minimum,
    "maximum": np.maximum,
}


def expression(expr: str, frame: pd.DataFrame) -> tuple[pd.Series, str]:
    if not isinstance(expr, str) or len(expr) > 300:
        raise ValueError("公式长度须不超过300字符")
    tree = ast.parse(expr, mode="eval")
    if len(list(ast.walk(tree))) > 65:
        raise ValueError("公式过于复杂")

    def visit(node, depth=0):
        if depth > 12:
            raise ValueError("公式嵌套过深")
        if isinstance(node, ast.Expression):
            return visit(node.body, depth + 1)
        if isinstance(node, ast.Name) and node.id in frame.columns:
            return frame[node.id]
        if (
            isinstance(node, ast.Constant)
            and type(node.value) in (int, float)
            and np.isfinite(node.value)
            and abs(node.value) <= 100
        ):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            return (-1 if isinstance(node.op, ast.USub) else 1) * visit(node.operand, depth + 1)
        if isinstance(node, ast.BinOp) and type(node.op) in BINOPS:
            return BINOPS[type(node.op)](visit(node.left, depth + 1), visit(node.right, depth + 1))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in FUNCS
            and not node.keywords
        ):
            return FUNCS[node.func.id](*[visit(a, depth + 1) for a in node.args])
        raise ValueError("只允许已知特征、四则运算和白名单函数，禁止任意代码或未来引用")

    result = visit(tree)
    if not isinstance(result, pd.Series):
        raise ValueError("因子必须引用特征，不能是常数")
    return result.replace([np.inf, -np.inf], np.nan), ast.dump(tree, include_attributes=False)


def validate_candidate(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("候选必须是 JSON 对象")
    for key in ["name_zh", "expression", "logic_zh", "market_regime", "failure_risks"]:
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            raise ValueError(f"缺少必填字段 {key}")
    if len(re.findall(r"[\u4e00-\u9fff]", raw["logic_zh"])) < 35:
        raise ValueError("中文逻辑解析不足：须说明输入、组合逻辑、方向与局限")
    if type(raw.get("expected_direction", 1)) is not int or raw.get(
        "expected_direction", 1
    ) not in (1, -1):
        raise ValueError("预期方向只能为 1 或 -1，不允许从测试集反推方向")
    # 任务身份、状态、来源由应用生成，模型不能通过额外字段覆盖它们。
    allowed = (
        "name_zh",
        "expression",
        "logic_zh",
        "market_regime",
        "failure_risks",
        "parent_factor_id",
    )
    return {
        **{k: raw[k] for k in allowed if k in raw},
        "expected_direction": raw.get("expected_direction", 1),
    }


def formula_explanation(expr: str) -> str:
    """按实际 AST 生成计算释义，帮助识别模型经济叙述中的符号理解偏差。"""
    tree = ast.parse(expr, mode="eval")
    names = sorted({n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id in FEATURES})
    text = "输入均为标准分：(原始值－之前60日均值)/之前60日样本标准差，至少30日预热。\n\n"
    text += "\n".join(f"- {n}：{FEATURES[n]}的标准分。" for n in names)
    rules = {
        ast.Add: "相加",
        ast.Sub: "相减",
        ast.Mult: "相乘",
        ast.Div: "相除（零分母记缺失）",
        "abs": "取绝对值",
        "tanh": "双曲正切压缩至(-1,1)，保留正负符号",
        "sqrt_abs": "绝对值开平方",
        "sign": "取符号(-1/0/1)",
        "minimum": "逐日取较小值",
        "maximum": "逐日取较大值",
    }
    operations = sorted(
        {
            rules[type(n.op)]
            for n in ast.walk(tree)
            if isinstance(n, ast.BinOp) and type(n.op) in rules
        }
        | {
            rules[n.func.id]
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in rules
        }
    )
    text += "\n\n算子：" + "；".join(operations)
    text += "。按公式括号与通常四则优先级逐日计算。负权重会翻转乘积符号，不只是减弱信号；标准分为正只表示原始特征高于历史均值，不能据此判定原始收益、趋势偏离或持仓变化为正。"
    text += "因子随后再次按历史窗口标准化、乘预期方向并按阈值映射为多/空/空仓。模型经济解释是待审查假设，计算释义与冻结公式确定实际行为。"
    return text


BASELINES = [
    {
        "name_zh": "人工基线：中期趋势",
        "expression": "trend20",
        "logic_zh": "以沪铜价格相对二十日均线的偏离衡量中期趋势。偏离越高假设趋势越强，采用正向信号持多，负向持空。该逻辑依赖趋势延续，在震荡和快速反转市场可能反复亏损。",
        "market_regime": "趋势行情",
        "failure_risks": "震荡反复与突发反转",
        "expected_direction": 1,
    },
    {
        "name_zh": "人工基线：短期反转",
        "expression": "reversal",
        "logic_zh": "以最近三个交易日收益取负衡量短期价格回归可能。近期下跌使因子升高，假设过度卖出后存在修复，因此采用正向买入；强趋势中价格可能持续原方向运动而导致失效。",
        "market_regime": "震荡行情",
        "failure_risks": "单边趋势与高换手成本",
        "expected_direction": 1,
    },
]
