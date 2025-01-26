# Python 베이스 이미지
FROM python:3.11-slim

# 작업 디렉토리 설정
WORKDIR /app

# 필요한 파일 복사
COPY requirements.txt ./
COPY . .

# 의존성 설치
RUN pip install --no-cache-dir -r requirements.txt

# 포트 노출
EXPOSE 8000

# 명령어 설정
CMD ["sh", "start_project.sh"]
