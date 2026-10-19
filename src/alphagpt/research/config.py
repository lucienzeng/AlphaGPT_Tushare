"""可序列化配置；所有实验保存配置副本，运行中不读取 UI 可变参数。"""

from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
SECRET_NAMES = ("TUSHARE_TOKEN", "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "MOONSHOT_API_KEY")


def load_credentials() -> dict[str, bool]:
    """只从 shell 子进程捕获所需变量；绝不打印 shell 输出或密钥。"""
    if any(not os.environ.get(k) for k in SECRET_NAMES):
        program = (
            "import os,json;print('CU_ENV:'+json.dumps({k:os.getenv(k,'') for k in "
            + repr(SECRET_NAMES)
            + "}))"
        )
        import shlex

        command = "set +x; source ~/.zshrc >/dev/null 2>&1; set +x; export " + " ".join(
            SECRET_NAMES
        )
        command += "; exec " + shlex.quote(sys.executable) + " -c " + shlex.quote(program)
        try:
            result = subprocess.run(
                ["/bin/zsh", "-f", "-c", command], capture_output=True, timeout=20
            )
            for line in result.stdout.decode(errors="replace").splitlines():
                if line.startswith("CU_ENV:"):
                    for key, value in json.loads(line[7:]).items():
                        if key in SECRET_NAMES and value and not os.environ.get(key):
                            os.environ[key] = value
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
    return {key: bool(os.environ.get(key)) for key in SECRET_NAMES}


@dataclass
class DownloadConfig:
    start: str = "2023-01-01"
    end: str = "2025-12-31"
    rpm: int = 30
    endpoint_rpm: dict[str, int] = field(default_factory=dict)
    timeout: int = 30
    retries: int = 3
    repair: bool = False
    warmup_days: int = 250
    metadata_ttl_hours: int = 24
    row_limits: dict[str, int] = field(default_factory=dict)
    tail_days: int = 0  # 默认关闭自动尾部复查，避免普通历史刷新额外请求。
    tail_check_hours: int = 24

    def validate(self) -> None:
        if date.fromisoformat(self.start) > date.fromisoformat(self.end):
            raise ValueError("下载开始日期不能晚于结束日期")
        if date.fromisoformat(self.end) >= date.today():
            raise ValueError("仅同步已完成交易日；结束日期须早于今天")
        if not 1 <= self.rpm <= 500 or not 0 <= self.retries <= 5:
            raise ValueError("请求频次需为 1～500，重试次数需为 0～5；实际权限以官方限制为准")
        if (
            self.timeout <= 0
            or self.warmup_days < 0
            or self.tail_days < 0
            or self.tail_check_hours < 1
            or self.metadata_ttl_hours < 1
        ):
            raise ValueError("超时、缓存期限和尾部复查周期必须为正，预热和尾部范围非负")
        for limits in (self.endpoint_rpm, self.row_limits):
            if not isinstance(limits, dict) or any(
                type(v) is not int or v <= 0 for v in limits.values()
            ):
                raise ValueError("接口频次和行数设置必须为正整数 JSON 对象")


@dataclass
class ModelProfile:
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com"
    key_env: str = "DEEPSEEK_API_KEY"
    protocol: str = "chat"
    timeout: int = 120
    max_tokens: int = 5000
    optional_params: dict = field(
        default_factory=lambda: {"temperature": 0.7, "response_format": {"type": "json_object"}}
    )


def profiles() -> dict[str, ModelProfile]:
    defaults = {
        "DeepSeek": ModelProfile(),
        "OpenAI": ModelProfile(
            "openai",
            "",
            "https://api.openai.com/v1",
            "OPENAI_API_KEY",
            "responses",
            optional_params={},
        ),
        "Kimi": ModelProfile(
            "kimi", "", "https://api.moonshot.cn/v1", "MOONSHOT_API_KEY", optional_params={}
        ),
        "自定义兼容接口": ModelProfile(
            "compatible", "", "", "CUSTOM_LLM_API_KEY", optional_params={}
        ),
    }
    path = ROOT / "models.json"
    if path.exists():
        for name, obj in json.loads(path.read_text()).items():
            defaults[name] = ModelProfile(**obj)
    return defaults


@dataclass
class BacktestConfig:
    capital: float = 1_000_000
    exposure: float = 0.8
    margin_cap: float = 0.35
    fee_mode: str = "rate"  # rate 为单边小数费率，per_lot 为单边元/手，historical 使用供应商参数
    fee: float = 0.00005
    broker_fee_per_lot: float = 0.0
    slippage_ticks: float = 1.0
    tick_size: float = 10.0
    signal_window: int = 60
    threshold: float = 0.5
    decision_lag: int = 2  # 历史发布时间未获证实时，t 数据在 t+2 交易日开盘执行
    delivery_buffer_days: int = 10
    fallback_margin: float = 0.20

    def validate(self) -> None:
        if self.capital <= 0 or not 0 < self.exposure <= 1 or not 0 < self.margin_cap <= 1:
            raise ValueError("资金须为正，名义敞口和保证金预算须处于 (0,1]")
        if (
            self.fee_mode not in ("rate", "per_lot", "historical")
            or min(self.fee, self.slippage_ticks, self.broker_fee_per_lot) < 0
        ):
            raise ValueError("费用模式无效或交易成本为负")
        if self.decision_lag < 1 or self.signal_window < 20 or self.threshold < 0:
            raise ValueError("成交延迟至少 1 个交易日，标准化窗口至少 20，阈值非负")
        if any(type(v) is not int for v in (self.decision_lag, self.signal_window, self.delivery_buffer_days)):
            raise ValueError("延迟、窗口和交割缓冲必须为整数")
        if self.tick_size <= 0 or not 0 < self.fallback_margin <= 1 or self.delivery_buffer_days < 0:
            raise ValueError("最小价位须为正，备用保证金比例须处于(0,1]，交割缓冲不得为负")
        import math
        if any(not math.isfinite(v) for v in asdict(self).values() if isinstance(v,(int,float))):
            raise ValueError('回测参数不能含NaN或无穷值')


@dataclass
class ExperimentConfig:
    snapshot: str
    train_start: str
    train_end: str
    valid_end: str
    test_end: str
    rounds: int = 1
    count: int = 10
    direction: str = "研究沪铜趋势、反转、波动与量价持仓结构的可解释时间序列因子"
    max_calls: int = 6
    token_budget: int = 500000
    correlation_limit: float = 0.98
    model: ModelProfile = field(default_factory=ModelProfile)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)

    curve: str = "CU.SHF"
    price_mode: str = "causal_ratio"
    feature_version: str = "futures-v2"
    use_templates: bool = False
    research_protocol: str = 'isolated-v1'
    candidate_budget: int = 30
    random_controls: int = 3

    def validate(self) -> None:
        if self.research_protocol not in ('isolated-v1','legacy-v1'):
            raise ValueError('未知研究协议')
        if self.research_protocol == 'isolated-v1' and self.backtest.decision_lag < 2:
            raise ValueError('历史发布时间未核实：新研究协议要求保守延迟至少2个交易日')
        if not 1 <= self.candidate_budget <= 1000 or self.rounds*self.count > self.candidate_budget:
            raise ValueError('模型候选数超过研究计划预算；请减少轮数/每轮数量，或明确调整计划预算')
        if not 0 <= self.random_controls <= 30:
            raise ValueError('随机对照数量必须为0～30')
        if self.price_mode not in ("causal_ratio", "raw") or self.feature_version not in ("legacy-v1", "futures-v2"):
            raise ValueError("曲线或特征版本无效")
        dates = list(
            map(
                date.fromisoformat,
                [self.train_start, self.train_end, self.valid_end, self.test_end],
            )
        )
        if not dates[0] < dates[1] < dates[2] < dates[3]:
            raise ValueError("训练开始 < 训练结束 < 验证结束 < 测试结束，区间不得重叠")
        if not 1 <= self.rounds <= 20 or not 1 <= self.count <= 50:
            raise ValueError("轮数 1～20，每轮数量 1～50")
        if self.max_calls < self.rounds or self.token_budget < 100:
            raise ValueError("调用预算不足以执行设定轮数")
        self.backtest.validate()

    @classmethod
    def from_dict(cls, d: dict) -> "ExperimentConfig":
        d = dict(d)
        # 旧任务未保存版本时沿用旧特征，不能在恢复或重测时悄悄升级。
        d.setdefault("feature_version", "legacy-v1")
        d.setdefault('research_protocol','legacy-v1')
        if d['research_protocol'] == 'legacy-v1':
            d.setdefault('random_controls',0)
            d.setdefault('candidate_budget',max(30,d.get('rounds',1)*d.get('count',10)))
        d["model"] = ModelProfile(**d.get("model", {}))
        d["backtest"] = BacktestConfig(**d.get("backtest", {}))
        return cls(**d)
