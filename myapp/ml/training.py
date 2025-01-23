import os
import pandas as pd
import pickle

from celery import shared_task
from xgboost import XGBRegressor
from datetime import timedelta
from django.utils.timezone import now
from django.shortcuts import get_object_or_404
from myapp.models import Site, ResponseTimeLog
from myproject import settings

@shared_task
def train_site_model(site_domain):
    """
    특정 사이트의 로그 데이터를 학습하여 모델 저장 (사이트 도메인 기반)
    """
    site = get_object_or_404(Site, domain=site_domain)
    logs = ResponseTimeLog.objects.filter(site=site).order_by('timestamp')

    # 최소 데이터 갯수 확인
    if logs.count() < 30:
        print(f"[INFO] Not enough data to train the model for site: {site.domain}")
        return None

    # 데이터프레임 변환
    data = [{"timestamp": log.timestamp, "response_time": log.response_time} for log in logs]
    df = pd.DataFrame(data)
    df['timestamp'] = pd.to_datetime(df['timestamp'])  # Ensure datetime format
    df['hour'] = df['timestamp'].dt.hour
    df['dayofweek'] = df['timestamp'].dt.dayofweek
    df['rolling_mean'] = df['response_time'].rolling(window=20, min_periods=1).mean()
    df['rolling_std'] = df['response_time'].rolling(window=20, min_periods=1).std().fillna(0.0)

    # 학습 데이터 준비
    X = df[['hour', 'dayofweek', 'rolling_mean', 'rolling_std']]
    y = df['response_time']

    split_idx = int(len(X) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

    # 모델 학습
    model = XGBRegressor(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)

    # 파일 이름에 사이트 도메인 포함
    safe_domain = site_domain.replace(".", "_")
    model_path = os.path.join(settings.MODEL_STORAGE_DIR, f"{safe_domain}.pkl")

    # 모델 저장
    with open(model_path, 'wb') as f:
        pickle.dump(model, f)

    print(f"[INFO] Trained model saved at: {model_path}")
    return model


def update_site_model(site_domain):
    """
    기존 모델에 최근 1분 데이터를 추가 학습
    """
    site = get_object_or_404(Site, domain=site_domain)
    logs = ResponseTimeLog.objects.filter(
        site=site,
        timestamp__gte=now() - timedelta(minutes=1)
    ).order_by('timestamp')

    if logs.count() < 10:
        print(f"[INFO] Not enough data to update the model for site: {site.domain}")
        return None

    # 데이터프레임 생성
    data = [{"timestamp": log.timestamp, "response_time": log.response_time} for log in logs]
    df = pd.DataFrame(data)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['hour'] = df['timestamp'].dt.hour
    df['dayofweek'] = df['timestamp'].dt.dayofweek
    df['rolling_mean'] = df['response_time'].rolling(window=20, min_periods=1).mean()
    df['rolling_std'] = df['response_time'].rolling(window=20, min_periods=1).std().fillna(0.0)

    # 학습 데이터 준비
    X = df[['hour', 'dayofweek', 'rolling_mean', 'rolling_std']]
    y = df['response_time']

    # 기존 모델 로드
    safe_domain = site_domain.replace(".", "_")
    model_path = os.path.join(settings.MODEL_STORAGE_DIR, f"{safe_domain}.pkl")
    if not os.path.exists(model_path):
        print(f"[ERROR] Model file not found: {model_path}")
        return None
    with open(model_path, 'rb') as f:
        existing_model = pickle.load(f)

    # 모델 업데이트
    model = XGBRegressor(n_estimators=100, random_state=42)
    model.fit(X, y, xgb_model=existing_model)

    # 업데이트된 모델 저장
    with open(model_path, 'wb') as f:
        pickle.dump(model, f)

    print(f"[INFO] Updated model saved at: {model_path}")
    return model