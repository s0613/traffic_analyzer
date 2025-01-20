# Description: Django Signal을 이용한 크롤링 시작 및 주기적 크롤링 업데이트 스케줄링
from django.db.models.signals import post_save
from django.dispatch import receiver
from myapp.models import Site
from myapp.tasks import crawl_site, schedule_crawl_task

@receiver(post_save, sender=Site)
def start_crawl_on_new_site(sender, instance, created, **kwargs):
    """
    새로운 Site가 추가되거나 수정될 때 호출.
    """
    if created:  # 새로 생성된 경우에만 크롤링 시작
        print(f"[SIGNAL] New site added: {instance.domain}")
        crawl_site.delay(instance.domain)  # 즉시 크롤링 실행

        # 스케줄 태스크 재등록 (필요 시 주기적 크롤링 업데이트)
        schedule_crawl_task.apply_async(countdown=5)
