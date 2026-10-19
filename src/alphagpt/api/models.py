"""多供应商接入；DeepSeek 复用原项目客户端，统一记录原始响应与用量。"""

from dataclasses import asdict
import json
import os
import re
import time
from openai import OpenAI
from alphagpt.api.deepseek_client import DeepSeekClient
from alphagpt.research.config import ModelProfile
from alphagpt.research.jobs import Context
from alphagpt.research.storage import identifier, now


def parse_candidates(content: str) -> list[dict]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("factors"), list):
        raise ValueError("模型必须返回包含 factors 数组的 JSON 对象")
    return data["factors"]


class ModelClient:
    def __init__(self, profile: ModelProfile, ctx: Context):
        self.profile, self.ctx = profile, ctx
        if not profile.model or not profile.base_url:
            raise ValueError("请填写实际可用的模型 ID 和 Base URL")
        key = os.environ.get(profile.key_env)
        if not key:
            raise ValueError(f"未配置 {profile.key_env}，不会自动切换模型")
        if profile.provider == "deepseek":
            self.client = DeepSeekClient(key, profile.base_url, profile.model).client.with_options(
                timeout=profile.timeout, max_retries=0
            )
        else:
            self.client = OpenAI(
                api_key=key, base_url=profile.base_url, timeout=profile.timeout, max_retries=0
            )

    def call(self, prompt: str, max_calls: int = 6, token_budget: int = 500000) -> str:
        self.ctx.check()
        previous = [x for x in self.ctx.store.list("calls") if x["task"] == self.ctx.id]
        used = sum(x.get("total_tokens", 0) or 0 for x in previous)
        if (
            len(previous) >= max_calls
            or used + self.profile.max_tokens + len(prompt) // 2 > token_budget
        ):
            raise ValueError("已达到模型调用/Token预算，停止发出新请求")
        key, start = identifier("call"), time.monotonic()
        record = {
            "task": self.ctx.id,
            "profile": asdict(self.profile),
            "prompt": prompt,
            "created": now(),
            "status": "calling",
        }
        self.ctx.store.put("calls", key, record)
        self.ctx.progress(
            "等待模型响应",
            model=self.profile.model,
            call_id=key,
            calls=len(previous) + 1,
            tokens_used=used,
        )
        try:
            if self.profile.protocol == "responses":
                response = self.client.responses.create(
                    model=self.profile.model,
                    input=prompt,
                    max_output_tokens=self.profile.max_tokens,
                    **self.profile.optional_params,
                )
                content = response.output_text
            elif self.profile.protocol == "chat":
                response = self.client.chat.completions.create(
                    model=self.profile.model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=self.profile.max_tokens,
                    **self.profile.optional_params,
                )
                content = response.choices[0].message.content or ""
            else:
                raise ValueError("协议只支持 chat 或 responses")
            usage = response.usage.model_dump() if response.usage else {}
            record.update(
                status="succeeded",
                raw_response=response.model_dump(mode="json"),
                content=content,
                total_tokens=usage.get("total_tokens", 0),
                usage=usage,
                actual_model=response.model,
                elapsed_seconds=round(time.monotonic() - start, 3),
            )
            self.ctx.store.put("calls", key, record)
            self.ctx.log("model_response", call_id=key, **record)
            self.ctx.progress(
                "模型响应已保存",
                calls=len(previous) + 1,
                tokens_used=used + (record["total_tokens"] or 0),
                actual_model=response.model,
            )
            return content
        except Exception as e:
            record.update(
                status="failed", error=str(e), elapsed_seconds=round(time.monotonic() - start, 3)
            )
            self.ctx.store.put("calls", key, record)
            self.ctx.log("model_error", call_id=key, **record)
            raise


def generation_prompt(count: int, direction: str, feature_info: dict, feedback: list[dict]) -> str:
    from alphagpt.factor.specs import SPECS, describe
    feature_info = {name: describe(name) if name in SPECS else text for name,text in feature_info.items()}
    return f"""你是沪铜日频时间序列因子研究员。提出可证伪假设，不保证盈利。只返回 JSON 对象。
研究方向：{direction}
可用特征如下；非_raw及非生命周期标志列为历史标准分，_raw列保留原始方向，days_to_last_trade/days_since_roll为天数，is_roll为当日已发生标志。当前值在盘后才可得：{json.dumps(feature_info, ensure_ascii=False)}
注意标准分列0表示历史均值，负数表示低于历史均值；波动率、成交量、持仓等标准分也可能为负。原始收益/持仓变化列正负才表示实际涨跌/增减。不得调用shift、访问标签、使用未来换月日期；方向、强度与风险门控须区分。每个组合最多4个基础特征。
因此 tanh(volatility) 可能为负，不能解释为正向波动权重；若需非负门控可使用 (1+tanh(volatility))/2。
中文解析必须解释标准分含义和每一项符号变化，不得把标准化特征当原始正数。
只允许 + - * / 和 abs(x), tanh(x), sqrt_abs(x), sign(x), minimum(a,b), maximum(a,b)。
禁止任何其他函数、窗口、时间位移、属性访问、截面排名、未来数据。最多300字符、简单组合，避免除近零值。
每个候选必须有完整中文逻辑，逐项解释公式中的输入/算子、预期方向、成立条件和局限。持仓增加不等于单向资金流入。
生成 {count} 个不同因子；expected_direction 只能为1或-1；parent_factor_id 可为空。
严格输出格式：{{"factors":[{{"name_zh":"中文名称","expression":"trend20 * tanh(volume_ratio)","logic_zh":"至少约80字、与公式一致的中文经济逻辑解析，明确这只是待验证假设。","expected_direction":1,"market_regime":"适用行情","failure_risks":"失效风险","parent_factor_id":null}}]}}
下面仅为先前训练开发反馈与淘汰原因，不含独立验证或最终测试指标。禁止照抄已有公式，提出不同或改进的假设：
{json.dumps(feedback[-30:], ensure_ascii=False)}
"""
