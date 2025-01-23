import random
import time as _time
import redis
import requests
from celery import shared_task
from django.core.cache import cache
from django.utils.timezone import now
from myapp.ml.training import train_site_model
from myapp.models import Site, ResponseTimeLog

redis_client = redis.StrictRedis(host='localhost', port=6379, db=0)

def normalize_domain_for_db(domain: str) -> str:
    return domain.replace("https://", "").replace(".", "_")

def denormalize_domain_from_db(domain: str) -> str:
    return f"https://{domain.replace('_', '.')}"

@shared_task
def set_event_mode(site_domain: str, enable: bool):
    """
    이벤트 모드를 활성화 또는 비활성화합니다.
    """
    if enable:
        cache.set(f"fast_mode_{site_domain}", True, timeout=60)
        print(f"[INFO] Fast mode activated for site {site_domain}.")
    else:
        cache.delete(f"fast_mode_{site_domain}")
        print(f"[INFO] Fast mode deactivated for site {site_domain}.")

@shared_task
def crawl_site(domain: str):
    denormalized_domain = denormalize_domain_from_db(domain)
    try:
        t0 = now().timestamp()
        response = requests.get(denormalized_domain, timeout=10)
        response_time = now().timestamp() - t0
        status_code = response.status_code
    except requests.exceptions.Timeout:
        print(f"[ERROR] Timeout while crawling {denormalized_domain}")
        response_time = -1
        status_code = None
    except requests.exceptions.SSLError:
        print(f"[ERROR] SSL error while crawling {denormalized_domain}")
        response_time = -1
        status_code = None
    except requests.RequestException as e:
        print(f"[ERROR] Failed to crawl {denormalized_domain}: {e}")
        response_time = -1
        status_code = None

    site_obj = Site.objects.filter(domain=domain).first()
    if site_obj:
        if response_time != -1:  # Only log valid response times
            ResponseTimeLog.objects.create(
                site=site_obj,
                timestamp=now(),
                response_time=round(response_time, 3)
            )
            print(f"[CRAWL] {denormalized_domain} => {response_time:.3f}s (status: {status_code})")
        else:
            print(f"[CRAWL] {denormalized_domain} => Failed to crawl")
    else:
        print(f"[ERROR] Site not found for domain: {domain}")

@shared_task
def update_predictions_and_train(site_domain: str, release_time):
    """
    release_time을 인자로 받아 Fast Mode 동작.
    """
    site = Site.objects.filter(domain=site_domain, active=True).first()
    if not site:
        print(f"[ERROR] Site not found or inactive: {site_domain}")
        return

    current_time = now()

    # release_time이 None인 경우 처리
    if not release_time:
        print(f"[INFO] Release time not provided for site: {site.domain}")
        return

    # 이미 release_time이 지난 경우에는 빠른 모드 실행 불필요
    if current_time >= release_time:
        print(f"[INFO] Release time has passed for site: {site.domain}")
        return

    # 총 6번의 빠른 크롤링과 모델 재학습
    for _ in range(6):
        crawl_site(site_domain)
        print(f"[INFO] Re-training model for site: {site.domain}")
        train_site_model.delay(site_domain)
        _time.sleep(10)

    print(f"[INFO] Completed fast-mode crawling and training for site: {site.domain}")

@shared_task
def schedule_regular_crawling():
    """
    활성화된 사이트마다 정기 크롤링을 스케줄링.
    Fast Mode 중인 사이트는 스킵.
    """
    sites = Site.objects.filter(active=True)
    for site in sites:
        if cache.get(f"fast_mode_{site.domain}"):
            print(f"[INFO] Fast mode is active for site {site.domain}. Skipping regular crawling.")
            continue

        domain = normalize_domain_for_db(site.domain)
        delay = random.uniform(60, 180)  # 1~3분 랜덤 지연
        print(f"[SCHEDULE] Next crawl for {domain} in {delay:.1f} seconds.")
        crawl_site.apply_async(args=[domain], countdown=delay)

@shared_task
def daily_train_models():
    """
    하루 한 번씩 모든 활성 사이트에 대한 모델 학습.
    """
    sites = Site.objects.filter(active=True)
    for site in sites:
        try:
            print(f"[INFO] Training model for site: {site.domain}")
            train_site_model(site.domain)
        except Exception as e:
            print(f"[ERROR] Failed to train model for site {site.domain}: {e}")
            continue

    print("[INFO] Completed daily model training for all sites.")

@shared_task
def activate_fast_mode(site_domain: str, release_time):
    """
    Fast Mode 활성화 태스크.
    이미 Fast Mode면 TTL 갱신 후 크롤링/학습 다시 수행.
    """
    if cache.get(f"fast_mode_{site_domain}"):
        print("[INFO] Fast mode is already activated. Renewing TTL and re-running tasks.")
        # Fast Mode 유지 시간을 새로 갱신(재설정)
        cache.set(f"fast_mode_{site_domain}", True, timeout=60)
        # 추가적으로 크롤링 & 재학습 재개
        update_predictions_and_train.delay(site_domain, release_time)
        return

    # 처음 Fast Mode 켜는 경우
    set_event_mode(site_domain, enable=True)
    update_predictions_and_train.delay(site_domain, release_time)
    print(f"[INFO] Fast mode activated for site {site_domain}.")

@shared_task
def deactivate_fast_mode(site_domain: str):
    """
    Fast Mode 비활성화 태스크.
    """
    set_event_mode(site_domain, enable=False)
    print(f"[INFO] Fast mode deactivated for site {site_domain}.")
