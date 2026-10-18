#!/bin/zsh
set -eu
cd "${0:A:h:h}"
if [[ ! -x .venv/bin/python ]]; then
  print '请先在项目内执行 uv sync --extra dev'
  exit 1
fi
# Python 凭据加载器从受控 shell 捕获所需变量，不回显密钥和 shell 配置。
mkdir -p runtime/logs
print '研究界面：http://127.0.0.1:8501；服务日志：runtime/logs/server.log'
exec .venv/bin/python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false >> runtime/logs/server.log 2>&1
