from django.db import models

class Site(models.Model):
    domain = models.CharField(max_length=255, unique=True)  # 사이트 도메인
    name = models.CharField(max_length=255, blank=True, null=True)  # 사이트 이름
    active = models.BooleanField(default=True)  # 활성화 여부

    def __str__(self):
        return f"{self.name or self.domain} (active={self.active})"

class ResponseTimeLog(models.Model):
    site = models.ForeignKey(Site, on_delete=models.CASCADE)  # Site 테이블과 연결
    timestamp = models.DateTimeField()  # 응답 시간
    response_time = models.FloatField()  # 응답 속도 (초 단위)

    def __str__(self):
        return f"{self.site.domain} | {self.timestamp} => {self.response_time}s"
