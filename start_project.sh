#!/bin/bash

# Virtual environment 활성화
source venv/bin/activate

python manage.py makemigrations
python manage.py migrate

# 정적 파일 수집
python manage.py collectstatic --noinput
# Django 서버 실행
echo "[INFO] Starting Django development server..."
python manage.py runserver &

# Celery Worker 실행 (백그라운드)
echo "[INFO] Starting Celery Worker..."
celery -A myproject worker --loglevel=info &

# Celery Beat 실행 (백그라운드)
echo "[INFO] Starting Celery Beat..."
celery -A myproject beat --loglevel=info &


