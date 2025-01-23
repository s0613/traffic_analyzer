from django.core.management.base import BaseCommand
from django_celery_beat.models import PeriodicTask, IntervalSchedule

class Command(BaseCommand):
    help = "Initialize Celery Beat schedule"

    def handle(self, *args, **options):
        try:
            # 1분마다 실행되는 스케줄 생성
            schedule_1min, _ = IntervalSchedule.objects.get_or_create(
                every=60,
                period=IntervalSchedule.SECONDS
            )

            # 24시간마다 실행되는 스케줄 생성
            schedule_24hours, _ = IntervalSchedule.objects.get_or_create(
                every=86400,
                period=IntervalSchedule.SECONDS
            )

            # 주기적 작업 생성: schedule_regular_crawling
            PeriodicTask.objects.get_or_create(
                interval=schedule_1min,
                name="Schedule regular crawling every 1 minute",
                task="myapp.tasks.schedule_regular_crawling"
            )

            # 주기적 작업 생성: daily_train_models
            PeriodicTask.objects.get_or_create(
                interval=schedule_24hours,
                name="Train all sites every 24 hours",
                task="myapp.tasks.daily_train_models"
            )

            self.stdout.write(self.style.SUCCESS("Celery Beat initialized successfully."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to initialize Celery Beat: {e}"))