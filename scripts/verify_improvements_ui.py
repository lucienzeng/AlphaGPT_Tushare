"""工作台四页冒烟，不触发下载、模型请求或新的最终测试。"""
from pathlib import Path
import json
from streamlit.testing.v1 import AppTest

app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=40).run()
report={}
assert not app.exception, [x.message for x in app.exception]
report['数据同步']='passed'
app.sidebar.radio[0].set_value('数据展示').run()
assert not app.exception, [x.message for x in app.exception]
report['数据展示']='passed'
app.sidebar.radio[0].set_value('因子挖掘').run()
assert not app.exception, [x.message for x in app.exception]
report['无效快照友好拦截']=[x.value for x in app.error]
snapshot=next(w for w in app.selectbox if w.label=='研究数据快照')
snapshot.set_value('cu_6bdd3416eb40e69dba65').run()
assert not app.exception, [x.message for x in app.exception]
assert not app.error, [x.value for x in app.error]
report['因子挖掘']='passed'
app.sidebar.radio[0].set_value('回测结果').run()
assert not app.exception, [x.message for x in app.exception]
report['回测结果']='passed'
Path('runtime/verification/improvements_ui.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False))
