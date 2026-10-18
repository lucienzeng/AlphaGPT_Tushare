"""最小请求对照；只输出 HTTP 状态、业务错误和行数，绝不记录鉴权载荷。"""

import os
import time
import requests
import tushare as ts
from alphagpt.research.config import load_credentials
from alphagpt.research.storage import Store, dumps

load_credentials()
store = Store()
params = {"exchange": "SHFE", "start_date": "20240102", "end_date": "20240102"}
api = ts.pro_api(os.environ["TUSHARE_TOKEN"], timeout=20)
api._DataApi__http_url = "https://api.waditu.com/dataapi"
try:
    frame = api.query("fut_trade_cal", **params)
    result = {
        "transport": "official_sdk_https",
        "rows": len(frame),
        "columns": list(frame.columns),
        "query_days": 1,
    }
except Exception as e:
    result = {"transport": "official_sdk_https", "error": str(e), "query_days": 1}
store.event("tushare_diagnostic", "single_day_probe", **result)
print(dumps(result), flush=True)
time.sleep(3)
with requests.Session() as session:
    for attempt in range(2):
        try:
            response = session.post(
                "https://api.tushare.pro",
                json={
                    "api_name": "fut_trade_cal",
                    "token": os.environ["TUSHARE_TOKEN"],
                    "params": params,
                    "fields": "",
                },
                timeout=20,
            )
            obj = response.json()
            result = {
                "transport": "official_rest_https_persistent_session",
                "attempt": attempt + 1,
                "http_status": response.status_code,
                "code": obj.get("code"),
                "message": obj.get("msg"),
                "rows": len((obj.get("data") or {}).get("items", [])),
                "query_days": 1,
            }
        except Exception as e:
            result = {
                "transport": "official_rest_https_persistent_session",
                "attempt": attempt + 1,
                "error": str(e),
                "query_days": 1,
            }
        store.event("tushare_diagnostic", "single_day_probe", **result)
        print(dumps(result), flush=True)
        time.sleep(3)
