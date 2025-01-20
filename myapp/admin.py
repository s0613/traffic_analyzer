from django.contrib import admin
from .models import Site, ResponseTimeLog
from django_celery_results.models import TaskResult
# 모델 등록
admin.site.register(Site)
admin.site.register(ResponseTimeLog)
