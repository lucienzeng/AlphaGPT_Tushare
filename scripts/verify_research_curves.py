"""真实冻结数据验收：只对已使用的2024开发样本联调模型，不解封新的保留区。"""
from dataclasses import asdict
from pathlib import Path
from datetime import datetime, timezone
import json
import hashlib
import subprocess
import pandas as pd
from alphagpt.research.config import load_credentials, ExperimentConfig
from alphagpt.research.storage import Store, dumps
from alphagpt.research.jobs import Manager
from alphagpt.research.cli import wait
from alphagpt.data.futures import load_snapshot
from alphagpt.data.curves import prepare_curve, build_curve_frame
from alphagpt.factor.research import features

load_credentials()
store=Store()
report={'started':datetime.now(timezone.utc).isoformat(),'purpose':'工程验收，不作为独立样本外盈利证据'}
# 不覆盖、不改写旧快照或旧实验。
old_paths=[p for folder in ['snapshots','experiments'] for p in (store.root/folder).glob('**/*') if p.is_file()]
old_hash={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in old_paths}
curves=[]
for snap in store.list('snapshots'):
    data=load_snapshot(store,snap['id'])
    selected,key=prepare_curve(store,snap['id'],data,'CU.SHF','causal_ratio')
    panel=selected['signal_curve']
    f,_=features(selected,version='futures-v2')
    for position in [len(panel)//2,len(panel)-20]:
        end=panel.trade_date.iloc[position]
        truncated={k:v.loc[v.trade_date.le(end)].copy() if 'trade_date' in v else v.copy() for k,v in data.items()}
        short=build_curve_frame(truncated)
        pd.testing.assert_frame_equal(panel.loc[:position].reset_index(drop=True),short)
        short_features,_=features(truncated,version='futures-v2')
        pd.testing.assert_frame_equal(f.loc[:end],short_features)
    curves.append({'snapshot':snap['id'],'curve_id':key,'rows':len(panel),'features':len(f.columns),'prefix_checks':2})
report['curves']=curves
old_namespace={}
exec(compile(subprocess.check_output(['git','show','HEAD:src/alphagpt/factor/research.py'],text=True), 'git-HEAD-feature-baseline', 'exec'),old_namespace)
for snap in store.list('snapshots'):
    original=load_snapshot(store,snap['id'])
    old_features,_=old_namespace['features'](original)
    current_features,_=features(original,version='legacy-v1')
    pd.testing.assert_frame_equal(old_features,current_features)
report['legacy_feature_values_identical']=True
manager=Manager(store)
try:
    # 沿用已看过的2024区间做工程验证，避免污染新下载的2025—2026保留测试区。
    old=store.list('runs')[-1]['config']
    cfg=ExperimentConfig.from_dict(old)
    cfg.curve='CU.SHF';cfg.price_mode='causal_ratio';cfg.feature_version='futures-v2';cfg.use_templates=True
    cfg.rounds=1;cfg.count=2;cfg.max_calls=3;cfg.token_budget=500000
    cfg.validate()
    task=manager.submit('mine',asdict(cfg));report['task']=task
    print('真实验证任务：'+task,flush=True)
    report['result']=wait(store,task)
    generated=[x for x in store.list('factors') if x.get('task')==task]
    report['factors']=[{k:f.get(k) for k in ['id','source','name_zh','status','reason','curve_id','feature_version']} for f in generated]
    assert sum(f.get('source')=='方案模板' for f in generated)==8
    assert any(f.get('round',0)>0 for f in generated)
    report['export_bytes']=len(__import__('alphagpt.research.workflow',fromlist=['export_experiment']).export_experiment(store,next(f['experiment'] for f in generated if f.get('experiment'))))
    report['old_artifacts_unchanged']=all(p.exists() and hashlib.sha256(p.read_bytes()).hexdigest()==old_hash[str(p)] for p in old_paths)
    assert report['old_artifacts_unchanged']
    with store.connect() as db:report['sqlite_check']=db.execute('pragma quick_check').fetchone()[0]
    report['status']='passed'
finally:
    manager.close()
    report['finished']=datetime.now(timezone.utc).isoformat()
    (store.root/'verification/research_curves_acceptance.json').write_text(dumps(report)+'\n')
print(dumps(report),flush=True)
