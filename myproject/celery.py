# Celery 설정을 구성하고 Celery 앱을 생성하는 파일
import os
from celery import Celery

# Django 설정을 기본값으로 지정
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')

app = Celery('myproject')

# settings.py에서 시작하는 "CELERY" 키를 Celery 설정으로 사용
app.config_from_object('django.conf:settings', namespace='CELERY')

# 앱에서 태스크를 자동으로 검색
app.autodiscover_tasks()
