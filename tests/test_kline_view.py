"""实际前端脚本的交互回归：防止周期溢出和控件不再更新图表。"""
from pathlib import Path
import json
import shutil
import subprocess
import pytest
from alphagpt.visualization.kline_view import _TEMPLATE


def test_frontend_controls_and_chart_initialization(tmp_path):
    node = shutil.which('node')
    if not node:
        pytest.skip('前端交互逻辑验证需要 Node.js')
    script = _TEMPLATE.rsplit('<script>', 1)[1].split('</script>', 1)[0]
    script = script.replace('__DATA__', json.dumps(dict(contracts=[], defaults=['MA','VOL'], chartHeight=460)))
    script = script.replace('__META__', json.dumps(dict(MA=dict(main=True), VOL=dict(main=False), RSI=dict(main=False))))
    target = tmp_path / 'kline.js'
    target.write_text(script)
    result = subprocess.run([node, str(Path(__file__).with_name('kline_ui_harness.cjs')), str(target)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
