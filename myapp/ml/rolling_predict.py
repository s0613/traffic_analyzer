import os
import pickle
import pandas as pd
from datetime import timedelta
from django.utils.timezone import now
from django.shortcuts import get_object_or_404
from myapp.models import ResponseTimeLog, Site

def load_site_model(site_domain):
    """
    저장된 모델 파일 로드
    """
    model_path = f"{site_domain}.pkl"
    if not os.path.exists(model_path):
        print(f"[ERROR] Model file not found: {model_path}")
        return None
    with open(model_path, 'rb') as f:
        return pickle.load(f)

def get_rolling_stats(site_domain, t, window_seconds=60):
    """
    도메인 이름 기반으로 롤링 통계를 계산.
    """
    site = get_object_or_404(Site, domain=site_domain)
    start_time = t - timedelta(seconds=window_seconds)

    qs = ResponseTimeLog.objects.filter(
        site=site,
        timestamp__gte=start_time,
        timestamp__lte=t
    ).order_by('timestamp')

    if not qs.exists():
        return 0.0, 0.0

    response_times = [obj.response_time for obj in qs]
    rolling_mean = sum(response_times) / len(response_times)
    rolling_std = (
        sum((x - rolling_mean) ** 2 for x in response_times) / len(response_times)
    ) ** 0.5
    return rolling_mean, rolling_std

def find_best_entry_time(site_domain, current_time, release_time):
    """
    발매시간 전 최적 진입 타이밍 예측 (1초 간격).
    - current_time < t < release_time 범위를 1초 단위로 탐색한다.
    - 시작 지점(current_time)과 끝 지점(release_time)은 제외.
    - 모든 예측값이 동일하더라도, 그중 첫 번째로 발견된 최소값 시점을 반환.
    - delta_seconds < 2면 '사이 구간'이 없으므로 None 반환.
    """

    model = load_site_model(site_domain)
    if not model:
        return None

    delta_seconds = int((release_time - current_time).total_seconds())
    # current_time과 release_time 사이에 1초 이상 차이 나야 '사이' 구간이 있음
    if delta_seconds < 2:
        return None

    best_time = None
    best_prediction = float('inf')

    # (1) 기존 로직: current_time+1초 ~ release_time-1초 구간을 1초씩 탐색
    for offset in range(1, delta_seconds):
        t = current_time + timedelta(seconds=offset)

        rolling_mean, rolling_std = get_rolling_stats(site_domain, t, 60)
        if rolling_mean is None or rolling_std is None:
            rolling_mean, rolling_std = 0.0, 0.0

        hour = t.hour
        dayofweek = t.weekday()
        X = pd.DataFrame(
            [[hour, dayofweek, rolling_mean, rolling_std]],
            columns=['hour', 'dayofweek', 'rolling_mean', 'rolling_std']
        )
        predicted_response = model.predict(X)[0]

        if predicted_response < best_prediction:
            best_prediction = predicted_response
            best_time = t

    # (2) 루프 후 보정 로직: best_time이 혹시 범위를 벗어나면 '클램핑'
    if best_time is not None:
        lowest_bound = current_time + timedelta(seconds=1)
        highest_bound = release_time - timedelta(seconds=1)

        # 혹시 lowest_bound > highest_bound면 구간이 없음 → None
        if lowest_bound > highest_bound:
            best_time = None
        else:
            # best_time이 lowest_bound보다 작으면 lowest_bound로 맞춤
            if best_time < lowest_bound:
                best_time = lowest_bound

            # best_time이 highest_bound보다 크면 highest_bound로 맞춤
            if best_time > highest_bound:
                best_time = highest_bound

            # 그래도 혹시 current_time 이상 & release_time 이하인지 최종 검사
            if not (current_time < best_time < release_time):
                best_time = None

    return best_time
