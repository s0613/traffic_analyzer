#!/bin/bash

## Virtual environment 활성화
#source venv/bin/activate

## Django 마이그레이션 실행
#echo "[INFO] Applying Django migrations..."
#python manage.py migrate

# Django 서버 실행
echo "[INFO] Starting Django development server..."
python manage.py runserver 0.0.0.0:8000 &

# Celery Worker 실행 (백그라운드)
echo "[INFO] Starting Celery Worker..."
celery -A myproject worker --loglevel=info &

# Celery Beat 실행 (백그라운드)
echo "[INFO] Starting Celery Beat..."
celery -A myproject beat --loglevel=info &

# FastAPI 서버 실행 (백그라운드)
echo "[INFO] Starting FastAPI server on port 8001..."
uvicorn main:app --host 0.0.0.0 --port 8001 &
