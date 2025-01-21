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

def set_event_mode(mode: str):
    if mode == "fast":
        cache.set("FAST_MODE", "1", timeout=60)
        print("[INFO] Fast mode activated.")
    elif mode == "regular":
        cache.set("FAST_MODE", "0")
        print("[INFO] Regular mode activated.")
    else:
        print("[ERROR] Invalid mode specified.")

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
def deactivate_fast_mode(site_id: int):
    set_event_mode("regular")
    cache.delete(f"fast_mode_{site_id}")
    print(f"[INFO] Fast mode deactivated for site {site_id}.")

@shared_task
def update_predictions_and_train(site_id: int):
    site = Site.objects.filter(id=site_id, active=True).first()
    if not site:
        print(f"[ERROR] Site not found or inactive: {site_id}")
        return

    release_time = site.release_time
    current_time = now()

    if not release_time or current_time >= release_time:
        print(f"[INFO] Release time has passed or not set for site: {site.domain}")
        return

    domain = normalize_domain_for_db(site.domain)

    for _ in range(6):
        crawl_site(domain)  # 크롤링 수행
        print(f"[INFO] Re-training model for site: {site.domain}")
        train_site_model.delay(site.id)  # 비동기적으로 모델 학습
        _time.sleep(10)

    print(f"[INFO] Completed fast-mode crawling and training for site: {site.domain}")

@shared_task
def schedule_regular_crawling():
    if cache.get("FAST_MODE") == "1":
        print("[INFO] Fast mode is active. Skipping regular crawling.")
        return

    sites = Site.objects.filter(active=True)
    for site in sites:
        domain = normalize_domain_for_db(site.domain)
        delay = random.uniform(60, 180)
        print(f"[SCHEDULE] Next crawl for {domain} in {delay:.1f} seconds.")
        crawl_site.apply_async(args=[domain], countdown=delay)

@shared_task
def daily_train_models():
    sites = Site.objects.filter(active=True)
    for site in sites:
        try:
            print(f"[INFO] Training model for site: {site.domain}")
            train_site_model(site.id)
        except Exception as e:
            print(f"[ERROR] Failed to train model for site {site.domain}: {e}")
            continue

    print("[INFO] Completed daily model training for all sites.")

@shared_task
def activate_fast_mode(site_id: int):
    if cache.get("FAST_MODE") == "1":
        print("[INFO] Fast mode is already activated.")
        return

    set_event_mode("fast")
    update_predictions_and_train.delay(site_id)
    print(f"[INFO] Fast mode activated for site {site_id}.")

@shared_task
def deactivate_fast_mode():
    set_event_mode("regular")
    cache.delete("FAST_MODE")
    print("[INFO] Fast mode deactivated.")