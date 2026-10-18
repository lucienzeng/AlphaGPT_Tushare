# AlphaGPT - AI驱动的量化因子生成与回测系统

受聚宽大佬**神启**启发，基于 DeepSeek AI 和 Tushare 数据源的量化因子生成和回测系统，支持 A 股市场的因子挖掘和策略回测。

## 项目特点

- 🤖 **AI驱动**: 使用 DeepSeek API 自动生成量化因子
- 📊 **Tushare数据源**: 支持 A 股市场数据获取
- 🎯 **多标的支持**: 支持同时对多个股票进行因子挖掘，提高因子泛化能力
- 🔧 **统一配置**: YAML 配置文件，便于管理
- 🔒 **安全性**: 支持环境变量管理敏感信息，使用 numexpr 安全计算
- 📈 **完整回测**: 内置回测引擎，支持多种绩效指标
- 📉 **IC分析**: 新增信息系数(IC)计算，评估因子预测能力
- 🔬 **滚动指标**: 支持滚动IC/夏普分析，评估因子稳定性
- 📊 **回撤分析**: 新增回撤曲线可视化
- 🎨 **增强可视化**: 2x3布局图表，展示更多维度信息
- 📁 **智能存储**: 按日期和股票代码自动组织结果文件
- 🏗️ **模块化设计**: 清晰的代码结构，易于维护和扩展

## 项目结构

```
alphagpt/
├── src/alphagpt/
│   ├── __init__.py
│   ├── main.py              # 主程序入口
│   ├── api/                 # API客户端模块
│   │   ├── __init__.py
│   │   └── deepseek_client.py
│   ├── config/              # 配置模块
│   │   ├── __init__.py
│   │   └── settings.py
│   ├── data/                # 数据处理模块
│   │   ├── __init__.py
│   │   ├── loader.py
│   │   └── features.py
│   ├── factor/              # 因子生成模块
│   │   ├── __init__.py
│   │   ├── generator.py
│   │   ├── operators.py
│   │   └── calculator.py    # 因子计算与评估
│   ├── backtest/            # 回测模块
│   │   ├── __init__.py
│   │   └── engine.py        # 回测引擎、IC计算
│   ├── visualization/       # 可视化模块
│   │   ├── __init__.py
│   │   └── plotter.py       # 2x3布局可视化
│   └── utils/               # 工具模块
│       ├── __init__.py
│       ├── logger.py
│       ├── seed.py
│       ├── constants.py
│       ├── output.py        # 输出目录管理
│       └── validators.py
├── pyproject.toml           # 项目配置文件
└── README.md                # 项目文档
```

## 安装

### 使用 pip

```bash
pip install -e .
```

或手动安装依赖：

```bash
pip install -r requirements.txt
```

或单独安装：

```bash
pip install numpy pandas matplotlib scipy requests tushare pyyaml openai numexpr
```

## 配置

### 1. 配置敏感信息（推荐使用环境变量）

**方式一：使用环境变量（推荐，更安全）**

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env 文件，填入真实的密钥
# TUSHARE_TOKEN=your_real_token
# DEEPSEEK_API_KEY=your_real_api_key
```

**方式二：使用配置文件**

```bash
# 复制配置文件模板
cp config.yaml.example config.yaml

# 编辑 config.yaml，填入真实的密钥
```

### 2. 编辑配置文件

编辑项目根目录下的 `config.yaml` 文件：

```yaml
# Tushare API 配置
tushare:
  token: "your_tushare_token_here"  # 在 https://tushare.pro 注册获取

# 数据配置
data:
  # 单个股票
  ts_code: "000001.SZ"      # 股票代码（平安银行）

  # 或使用多个股票（推荐，提高因子泛化能力）
  ts_codes: ["600519.SH", "000001.SZ", "600036.SH"]  # 多个股票代码列表

  start_date: "20200101"    # 开始日期 YYYYMMDD
  end_date: "20231231"      # 训练集结束日期 YYYYMMDD
  test_end: "20251231"      # 测试集结束日期 YYYYMMDD

# 因子生成配置
factor:
  max_seq_len: 6            # 最大序列长度
  min_op_count: 2           # 最小操作数
  num_factors: 10           # 生成因子数量

# DeepSeek API 配置
deepseek:
  api_key: "your_deepseek_api_key_here"
  base_url: "https://api.deepseek.com"
  model: "deepseek-chat"    # 或 deepseek-reasoner
  timeout: 60               # API 超时时间（秒）
  temperature: 0.7          # 生成温度

# 回测配置
backtest:
  position_scale: 0.3       # 仓位比例

# 日志配置
logging:
  level: "INFO"             # 日志级别: DEBUG, INFO, WARNING, ERROR
  log_file: "logs/alphagpt.log"

# 随机种子
random_seed: 42
```

### 3. 获取 Tushare Token

1. 访问 [Tushare Pro](https://tushare.pro/register) 注册账号
2. 在个人中心获取 API Token
3. 将 Token 填入 `config.yaml` 文件

### 4. 股票代码格式

Tushare 使用以下股票代码格式：

| 交易所 | 代码后缀 | 示例 |
|--------|----------|------|
| 上海证券交易所 | .SH | 600000.SH |
| 深圳证券交易所 | .SZ | 000001.SZ |
| 北京证券交易所 | .BJ | 430047.BJ |

### 5. 多标的配置（推荐）

支持同时对多个股票进行因子挖掘，提高因子的泛化能力：

```yaml
data:
  ts_codes: ["600519.SH", "000001.SZ", "600036.SH"]  # 多个股票代码列表
```

**优势**：
- 提高因子泛化能力，避免过拟合单一标的
- 增加训练数据量，提升因子稳定性
- 适用于跨标的策略开发

## 使用方法

### 命令行运行

```bash
# 运行完整的因子生成和回测
python -m alphagpt.main

# 或运行示例
python example.py
```

### 作为模块使用

```python
from alphagpt.config import Config
from alphagpt.data import DataLoader, FeatureEngineer
from alphagpt.factor import FactorGenerator

# 从 YAML 加载配置
config = Config.from_yaml('config.yaml')

# 加载数据
df = DataLoader.get_price_data(
    ts_code=config.ts_code,
    start=config.start_date,
    end=config.end_date,
    tushare_token=config.tushare_token
)

# 特征工程
df, features = FeatureEngineer.create_features(df)

# 生成因子
generator = FactorGenerator(
    api_key=config.api_key,
    base_url=config.base_url,
    model=config.model
)
factors = generator.generate_factors_with_deepseek(features)
```

## 模块说明

### API模块 (`api/`)
- `DeepSeekClient`: DeepSeek API客户端，处理API调用和重试逻辑

### 配置模块 (`config/`)
- `Config`: 集中管理所有配置参数，支持从 YAML 文件加载

### 数据模块 (`data/`)
- `DataLoader`: 数据加载器，支持从 Tushare 获取股票数据
- `FeatureEngineer`: 特征工程，创建技术指标特征

### 因子模块 (`factor/`)
- `FactorGenerator`: 因子生成器，使用AI生成因子表达式
- `FactorOperators`: 定义因子算子（ADD, SUB, MUL等）
- `FactorCalculator`:
  - 计算因子值和夏普比率
  - `evaluate_factor()`: 统一评估方法，使用滚动窗口归一化避免前视偏差
  - 支持IC计算

### 回测模块 (`backtest/`)
- `BacktestEngine`:
  - 回测引擎，计算策略绩效指标
  - 使用滚动窗口归一化（避免前视偏差）
  - `calculate_ic()`: 计算信息系数（IC）
  - `calculate_rolling_ic()`: 计算滚动IC

### 可视化模块 (`visualization/`)
- `ResultPlotter`:
  - 2x3布局增强可视化
  - 净值曲线、回撤曲线、滚动IC/夏普
  - 月度收益、仓位变化、绩效指标表
  - `plot_factor_correlation()`: 因子相关性热力图（可选）

### 工具模块 (`utils/`)
- `setup_logger`: 日志配置
- `set_seed`: 随机种子设置
- `create_run_output_dir`: 创建按日期和股票代码组织的输出目录

## 输出结果

### 目录结构

程序运行后会自动创建以下目录结构：

```
results/
├── 2026-01-25/              # 日期子文件夹
│   ├── 600519.SH_000001.SZ/ # 股票代码子文件夹
│   │   ├── performance.png  # 绩效图表（2x3布局）
│   │   └── summary.csv      # 结果汇总（含IC）
│   └── 600028.SH/
│       ├── performance.png
│       └── summary.csv
└── 2026-01-24/              # 历史运行记录
    └── ...
```

### 输出文件说明

1. **日志文件**: `logs/alphagpt.log` - 完整的运行日志，包含：
   - 配置信息（股票代码、日期范围、因子数量等）
   - 数据加载和特征工程详情
   - 生成的因子表达式列表
   - 每个因子的训练集/测试集评估结果（含IC）
   - 最佳因子的完整绩效指标

2. **绩效图表**: `results/YYYY-MM-DD/股票代码/performance.png`
   - 净值曲线对比
   - 回撤曲线
   - 滚动IC/夏普双轴图
   - 月度收益
   - 仓位变化
   - 绩效指标汇总表

3. **结果CSV**: `results/YYYY-MM-DD/股票代码/summary.csv`
   - 因子名称、表达式
   - 夏普比率、IC、年化收益
   - 最大回撤、信息比率、胜率、卡玛比率

### 日志示例

```
2026-01-25 17:01:17 - AlphaGPT 量化因子生成与回测系统启动
2026-01-25 17:01:17 - 配置信息:
2026-01-25 17:01:17 -   - 股票代码: ['600028.SH']
2026-01-25 17:01:17 -   - 因子生成数量: 10
2026-01-25 17:01:17 - 开始加载数据...
2026-01-25 17:01:17 - 特征工程完成: 生成 88 个特征
2026-01-25 17:02:28 - 成功生成 10 个因子表达式:
2026-01-25 17:02:28 -   Factor_1: ABS(ret_norm) + mom5_norm
2026-01-25 17:02:28 - 评估 Factor_1: ABS(ret_norm) + mom5_norm
2026-01-25 17:02:28 -   训练集夏普比率: -0.087
2026-01-25 17:02:28 -   测试集夏普比率: 0.173, IC: 0.045
2026-01-25 17:02:28 -   年化收益: 0.97%
2026-01-25 17:02:28 - 最佳因子: Factor_3
2026-01-25 17:02:28 - 表达式: NEG(ret5_norm) * SQRT(vol_chg_norm)
2026-01-25 17:02:28 -   夏普比率: 1.391
2026-01-25 17:02:28 -   信息系数(IC): 0.082
2026-01-25 17:02:28 -   年化收益率: 9.25%
```

## 新增功能

### IC（信息系数）分析
- 衡量因子值与未来收益的相关性
- IC值越接近1或-1，因子预测能力越强
- 支持滚动IC分析，评估因子稳定性

### 回撤曲线
- 可视化策略回撤过程
- 标注最大回撤位置
- 填充回撤区域，直观展示风险

### 滚动指标分析
- 滚动IC：评估因子预测能力的时间稳定性
- 滚动夏普：评估策略表现的时间稳定性
- 双轴图展示，便于对比分析

### 智能存储结构
- 按日期自动归档，便于历史对比
- 按股票代码分组，避免文件混乱
- 简化文件名，目录包含完整信息

## 常见问题

### 1. Tushare Token 未配置

如果未配置 Token，系统会使用模拟数据。请在 `config.yaml` 中配置有效的 Tushare Token。

### 2. 数据获取失败

- 检查网络连接
- 确认 Token 是否有效
- 检查股票代码格式是否正确
- 确认日期范围是否合理

### 3. API 调用失败

- 检查 DeepSeek API Key 是否有效
- 确认网络可以访问 API 服务
- 可以在配置中设置使用本地因子生成

### 4. IC值为NaN

- 可能是样本量不足
- 检查数据质量
- 确保因子值和收益率长度匹配

## 许可证

MIT License

## 贡献

欢迎提交Issue和Pull Request！

## 联系方式

如有问题，请提交Issue或联系项目维护者。
