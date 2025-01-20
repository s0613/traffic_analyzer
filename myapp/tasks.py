import random
import time

import requests
from celery import shared_task
from django.utils import timezone

from myapp.ml.training import train_site_model
from myapp.models import ResponseTimeLog
from myapp.models import Site

# 이벤트 모드 및 크롤링 관리 변수
IS_EVENT_MODE = {}  # 도메인 → 이벤트 모드 활성화 여부
next_check_time = {}  # 도메인 → 다음 크롤링 예정 시간 (epoch timestamp 값)

def normalize_domain_for_db(domain: str) -> str:
    """
    DB에서 사용되는 형식으로 도메인을 변환합니다.
    - https:// 제거
    - .(점)을 _로 변환
    """
    domain = domain.replace("https://", "").replace(".", "_")
    return domain

def denormalize_domain_from_db(domain: str) -> str:
    """
    DB에 저장된 도메인을 HTTP 요청에 사용할 형식으로 변환합니다.
    - _를 .으로 변환
    - https:// 추가
    """
    domain = domain.replace("_", ".")
    return f"https://{domain}"

@shared_task
def set_event_mode(domain: str, enable: bool = True):
    """
    특정 도메인의 이벤트 모드를 활성화하거나 비활성화합니다.
    """
    normalized_domain = normalize_domain_for_db(domain)
    IS_EVENT_MODE[normalized_domain] = enable
    mode_str = "EVENT" if enable else "NORMAL"
    print(f"[EVENT_MODE] {domain} set to {mode_str} mode.")

@shared_task
def crawl_site(domain: str):
    """
    사이트에 GET 요청을 보내고 응답 시간을 DB에 기록합니다.
    """
    normalized_domain = normalize_domain_for_db(domain)
    denormalized_domain = denormalize_domain_from_db(normalized_domain)

    t0 = time.time()
    try:
        response = requests.get(denormalized_domain, timeout=10)
        resp_time = time.time() - t0
        status_code = response.status_code
    except requests.RequestException as e:
        # 실패 시 응답 시간과 에러 로그 기록
        resp_time = time.time() - t0
        status_code = None
        print(f"[ERROR] Failed to crawl {denormalized_domain}: {e}")

    try:
        # 정규화된 도메인으로 DB 조회
        site_obj = Site.objects.get(domain=normalized_domain)
    except Site.DoesNotExist:
        print(f"[ERROR] Site not found in DB: {normalized_domain}")
        return

    # 응답 시간을 DB에 기록
    ResponseTimeLog.objects.create(
        site=site_obj,
        timestamp=timezone.now(),
        response_time=round(resp_time, 3)
    )

    # 상태 코드는 로그에 기록
    status_message = f"[CRAWL] {denormalized_domain} => {resp_time:.3f}s"
    if status_code:
        status_message += f" (status: {status_code})"
    print(status_message)

# 전역 변수로 상태 관리
IS_FAST_MODE = False

@shared_task
def best_entry_time_api_received():
    """
    API 요청을 처리하여 크롤링 속도를 2초로 변경하고 ML Training 속도를 10초로 설정합니다.
    """
    global IS_FAST_MODE
    IS_FAST_MODE = True
    print("[INFO] Fast mode activated. Crawling every 2 seconds, ML training every 10 seconds.")

    # Fast mode는 1분 후 자동 복구
    restore_default_mode.apply_async(countdown=60)

@shared_task
def restore_default_mode():
    """
    Fast mode 복구: 크롤링 10초, ML 학습 하루 1회로 복구.
    """
    global IS_FAST_MODE
    IS_FAST_MODE = False
    print("[INFO] Restored default mode. Crawling every 10 seconds, ML training daily.")

@shared_task
def schedule_crawl_task():
    """
    랜덤 간격으로 각 사이트를 크롤링
    - 이벤트 모드: 5~15초
    - 기본 모드: 60~180초
    """
    now = timezone.now()
    active_sites = Site.objects.filter(active=True)

    for site_obj in active_sites:
        domain = site_obj.domain
        if domain not in next_check_time:
            delay_sec = random.uniform(5, 15) if IS_EVENT_MODE.get(domain, False) else random.uniform(60, 180)
            next_check_time[domain] = now.timestamp() + delay_sec

        if now.timestamp() >= next_check_time[domain]:
            crawl_site.delay(domain)
            delay_sec = random.uniform(5, 15) if IS_EVENT_MODE.get(domain, False) else random.uniform(60, 180)
            next_check_time[domain] = now.timestamp() + delay_sec

@shared_task
def train_ml_model():
    """
    ML 학습 태스크를 동적으로 관리합니다.
    """
    global IS_FAST_MODE
    sites = Site.objects.filter(active=True)

    for site in sites:
        train_site_model(site.id)  # 각 사이트의 ML 모델 학습

    print(f"[INFO] ML 모델 학습 완료 in {'fast' if IS_FAST_MODE else 'default'} mode.")
