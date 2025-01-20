# This script initializes the Celery Beat schedule by creating a periodic task that runs every 10 seconds.
from django.core.management.base import BaseCommand
from django_celery_beat.models import PeriodicTask, IntervalSchedule

class Command(BaseCommand):
    help = "Initialize Celery Beat schedule"

    def handle(self, *args, **options):
        try:
            schedule, _ = IntervalSchedule.objects.get_or_create(
                every=10,
                period=IntervalSchedule.SECONDS
            )
            PeriodicTask.objects.get_or_create(
                interval=schedule,
                name="Train all sites every 10 seconds",
                task="myapp.tasks.run_ml_training"
            )
            self.stdout.write(self.style.SUCCESS("Celery Beat initialized successfully."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to initialize Celery Beat: {e}"))
