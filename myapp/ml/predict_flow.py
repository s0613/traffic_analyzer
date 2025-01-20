import os
import pickle
import pandas as pd
from datetime import timedelta
from django.utils.timezone import now
from myapp.models import ResponseTimeLog, Site
from .rolling_predict import get_rolling_stats


def load_model(site_id):
    """
    특정 사이트에 대한 머신러닝 모델을 로드합니다.
    """
    model_path = f"model_site_{site_id}.pkl"
    if not os.path.exists(model_path):
        print(f"[ERROR] 모델 파일이 없습니다: {model_path}")
        return None
    with open(model_path, 'rb') as f:
        return pickle.load(f)


def predict_best_entry_time(site_id, current_time, release_time, interval_seconds=1):
    """
    발매 시간 전 최적 진입 시점을 예측합니다.

    Args:
        site_id (int): 사이트 ID
        current_time (datetime): 현재 시간
        release_time (datetime): 발매 시간
        interval_seconds (int): 예측 간격 (초 단위)

    Returns:
        dict: 최적 진입 시점 정보 (시간, 예측 응답속도)
    """
    model = load_model(site_id)
    if not model:
        return {"optimal_time": None, "message": "모델 파일이 없습니다."}

    delta_seconds = int((release_time - current_time).total_seconds())
    if delta_seconds <= 0:
        return {"optimal_time": None, "message": "발매 시간이 현재 시간보다 빠릅니다."}

    best_time = None
    best_prediction = float('inf')

    for offset in range(0, delta_seconds, interval_seconds):
        t = current_time + timedelta(seconds=offset)
        rolling_mean, rolling_std = get_rolling_stats(site_id, t, window_seconds=60)

        hour = t.hour
        dayofweek = t.weekday()
        X = pd.DataFrame([[hour, dayofweek, rolling_mean, rolling_std]],
                         columns=['hour', 'dayofweek', 'rolling_mean', 'rolling_std'])
        predicted_response = model.predict(X)[0]

        if predicted_response < best_prediction:
            best_prediction = predicted_response
            best_time = t

    if best_time:
        return {
            "optimal_time": best_time,
            "message": f"최적 진입 시간은 {best_time.strftime('%H시 %M분 %S초')}입니다.",
            "predicted_response_time": round(best_prediction, 3)
        }
    else:
        return {"optimal_time": None, "message": "최적 진입 시간을 계산할 수 없습니다."}
