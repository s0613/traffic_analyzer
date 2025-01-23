import json
import logging
import threading
import pytz
from pytz import timezone, UTC
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils.dateparse import parse_datetime
from django.utils import timezone as django_timezone
from django.contrib.auth import authenticate
from django.core.cache import cache

from datetime import datetime, timedelta

# 필요한 Celery 태스크, 모델, 폼, 유틸 등을 import
from myapp.tasks import set_event_mode, deactivate_fast_mode, activate_fast_mode, update_predictions_and_train
from myapp.ml.rolling_predict import find_best_entry_time
from .models import Site
from .forms import AddSiteForm


logger = logging.getLogger(__name__)

def to_utc(dt, user_tz):
    """
    - dt(사용자 입력 datetime)가 naive인지 aware인지 판별
    - naive라면 user_tz로 localize 후 UTC로 변환
    - aware라면 바로 UTC로 astimezone 변환
    """
    if dt.tzinfo is None:
        # tzinfo가 없는 naive datetime
        return user_tz.localize(dt).astimezone(UTC)
    else:
        # tzinfo가 이미 있는 aware datetime
        return dt.astimezone(UTC)


@api_view(['POST'])
def best_entry_time_api(request):
    """
    사용자 현지 시간(current_time, release_time)을 받아,
    1) 사용자 시간대 → UTC 변환
    2) UTC → KST 변환 후 ML 모델 처리
    3) 결과(모델이 제공한 시간)를 다시 사용자 현지 시간대로 변환해 반환

    Fast Mode(캐시) 로직도 함께 포함
    """

    site_domain = request.data.get('site_domain')
    release_time_str = request.data.get('release_time')
    current_time_str = request.data.get('current_time')
    user_timezone_str = request.data.get('timezone', 'UTC')  # 사용자 시간대 문자열

    # 요청으로 들어온 주요 파라미터를 모두 로그로 남김
    logger.info(f"[Request In] site_domain={site_domain}, release_time_str={release_time_str}, "
                f"current_time_str={current_time_str}, user_timezone_str={user_timezone_str}")

    # 필수 파라미터 확인
    if not site_domain or not release_time_str or not current_time_str:
        logger.info("[Error] 필수 파라미터 누락")
        return Response(
            {"error": "필수 파라미터가 누락되었습니다: site_domain, release_time, current_time"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # 문자열 → datetime 파싱
    try:
        release_time = parse_datetime(release_time_str)
        user_current_time = parse_datetime(current_time_str)
    except (TypeError, ValueError):
        logger.info("[Error] 파싱 오류(올바르지 않은 시간 형식)")
        return Response(
            {"error": "올바르지 않은 시간 형식입니다. ISO 8601 형식(예: 2025-01-22T11:00:00Z)을 사용하세요."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # 파싱된 결과도 로그로 남김
    logger.info(f"[Parsed Times] release_time={release_time}, user_current_time={user_current_time}")

    if not release_time or not user_current_time:
        logger.info("[Error] 파싱된 시간 값이 None")
        return Response(
            {"error": "유효하지 않은 날짜/시간입니다."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # 릴리즈 시간이 현재 시간보다 과거거나 같으면 에러
    if release_time <= user_current_time:
        logger.info("[Error] 릴리즈 시간이 현재 시간과 같거나 과거")
        return Response(
            {"error": "릴리즈 시간은 현재 시간보다 미래여야 합니다."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # 사이트 도메인 확인
    if not Site.objects.filter(domain=site_domain).exists():
        logger.info("[Error] 존재하지 않는 사이트 도메인")
        return Response(
            {"error": f"사이트를 찾을 수 없습니다: {site_domain}"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # 사용자 시간대를 pytz 객체로 가져오기
    try:
        user_timezone = timezone(user_timezone_str)
    except Exception:
        logger.info("[Error] 유효하지 않은 사용자 시간대")
        return Response(
            {"error": f"유효하지 않은 시간대입니다: {user_timezone_str}"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # 1) 사용자 현지 시간 → UTC 변환
    try:
        user_current_time_utc = to_utc(user_current_time, user_timezone)
        release_time_utc = to_utc(release_time, user_timezone)
        logger.info(f"[UTC Times] user_current_time_utc={user_current_time_utc}, release_time_utc={release_time_utc}")
    except Exception as e:
        logger.info(f"[Error] 시간 변환 중 예외 발생: {str(e)}")
        return Response(
            {"error": f"시간 변환 중 오류가 발생했습니다: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # 2) UTC → KST 변환
    kst = timezone("Asia/Seoul")
    user_current_time_kst = user_current_time_utc.astimezone(kst)
    release_time_kst = release_time_utc.astimezone(kst)
    logger.info(f"[KST Times] user_current_time_kst={user_current_time_kst}, release_time_kst={release_time_kst}")

    # Fast Mode 여부 판단 (캐시에 fast_mode_{site_domain} 키로 저장)
    fast_mode_key = f"fast_mode_{site_domain}"
    is_fast_mode = cache.get(fast_mode_key)

    if is_fast_mode:
        # 캐시 갱신(갱신 시간 연장)
        cache.set(fast_mode_key, True, timeout=60)
        try:
            optimal_time_kst = find_best_entry_time(site_domain, user_current_time_kst, release_time_kst)
        except Exception as e:
            logger.info(f"[Error] 최적 진입 시간 계산 중 예외 발생(Fast Mode): {str(e)}")
            return Response(
                {"error": f"최적 진입 시간 계산 중 오류가 발생했습니다: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if optimal_time_kst:
            # KST → UTC → 사용자 현지 시간
            optimal_time_utc = optimal_time_kst.astimezone(UTC)
            optimal_time_local = optimal_time_utc.astimezone(user_timezone)
            logger.info(f"[Fast Mode] 최적 진입 시간(KST)={optimal_time_kst}, 사용자 현지 시간={optimal_time_local}")

            return Response({
                "optimal_time": optimal_time_local.isoformat(),
                "message": "[Fast Mode 유지 중] 진입 시간을 확인하세요.",
            }, status=200)
        else:
            logger.info("[Fast Mode] 최적 진입 시간 없음")
            return Response({
                "optimal_time": None,
                "message": "[Fast Mode 유지 중] 최적 진입 시간을 찾을 수 없습니다.",
            }, status=200)
    else:
        # Fast Mode가 아닌 경우
        try:
            optimal_time_kst = find_best_entry_time(site_domain, user_current_time_kst, release_time_kst)
        except Exception as e:
            logger.info(f"[Error] 최적 진입 시간 계산 중 예외 발생(Normal Mode): {str(e)}")
            return Response(
                {"error": f"최적 진입 시간 계산 중 오류가 발생했습니다: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if optimal_time_kst:
            # Fast Mode 활성화
            cache.set(fast_mode_key, True, timeout=60)
            activate_fast_mode.delay(site_domain, release_time)

            # KST → UTC → 사용자 현지 시간
            optimal_time_utc = optimal_time_kst.astimezone(UTC)
            optimal_time_local = optimal_time_utc.astimezone(user_timezone)
            logger.info(f"[Normal Mode] 최적 진입 시간(KST)={optimal_time_kst}, 사용자 현지 시간={optimal_time_local}")

            return Response({
                "optimal_time": optimal_time_local.isoformat(),
                "message": "최적 진입 시간을 확인하세요.",
            }, status=200)
        else:
            logger.info("[Normal Mode] 최적 진입 시간을 찾을 수 없음")
            return Response({
                "optimal_time": None,
                "message": "최적 진입 시간을 찾을 수 없습니다.",
            }, status=200)

def get_sites(request):
    """
    사이트 목록을 JSON 형태로 반환
    """
    sites = Site.objects.filter(active=True).values("domain", "name")
    return JsonResponse({"sites": list(sites)})


def site_list(request):
    """
    사이트 리스트 페이지
    """
    sites = Site.objects.all()
    return render(request, 'site_list.html', {"sites": sites})


def site_detail(request, site_domain):
    """
    특정 사이트 상세 페이지
    """
    site = get_object_or_404(Site, domain=site_domain)

    if request.method == "POST":
        release_time_str = request.POST.get("release_time")
        current_time_str = request.POST.get("current_time")
        if release_time_str and current_time_str:
            release_time = parse_datetime(release_time_str)
            current_time = parse_datetime(current_time_str)

            # 이벤트 모드 활성화
            set_event_mode.delay(site_domain, enable=True)

            # 최적 진입 시간 예측
            optimal_time = find_best_entry_time(site_domain, current_time, release_time)
            if optimal_time:
                formatted_time = optimal_time.strftime("%H시 %M분 %S초")
                return render(request, "site_detail.html", {
                    "site": site,
                    "optimal_time": formatted_time,
                    "release_time": release_time,
                    "current_time": current_time,
                })
            else:
                return render(request, "site_detail.html", {
                    "site": site,
                    "error": "최적 진입 시간을 계산할 수 없습니다.",
                })

    return render(request, "site_detail.html", {"site": site})


def toggle_event_mode(request, site_domain):
    """
    이벤트 모드 토글 (활성/비활성)
    """
    site = get_object_or_404(Site, domain=site_domain)
    is_active = site.active
    site.active = not is_active
    site.save()

    # 비동기 태스크 호출
    set_event_mode.delay(site_domain, enable=site.active)

    message = f"{site.domain}의 이벤트 모드가 {'활성화' if site.active else '비활성화'}되었습니다."
    if request.is_ajax():
        return JsonResponse({"message": message, "active": site.active})
    else:
        return redirect('site_list')


class LoginView(APIView):
    """
    로그인 API
    """

    def post(self, request, *args, **kwargs):
        email = request.data.get('email')
        password = request.data.get('password')
        user = authenticate(request, username=email, password=password)
        if user:
            return Response({"message": "Login successful"}, status=200)
        return Response({"error": "Invalid credentials"}, status=401)


@method_decorator(csrf_exempt, name='dispatch')
class AddURLView(View):
    """
    사이트(도메인) 추가 API
    """

    def post(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body)
            domain = data.get('domain')
            name = data.get('name', domain)

            if not domain:
                return JsonResponse({"error": "Domain is required."}, status=400)

            # URL에서 `https://` 제거
            sanitized_domain = domain.replace("https://", "")

            # '.'을 '_'로 바꾸는 로직: 필요 시 주석 처리하거나 수정할 수 있음
            # sanitized_domain = sanitized_domain.replace(".", "_")

            site, created = Site.objects.get_or_create(
                domain=sanitized_domain,
                defaults={"name": name, "active": True}
            )
            return JsonResponse({
                "message": "URL added successfully.",
                "site": {
                    "id": site.id,
                    "domain": site.domain,
                    "name": site.name,
                    "active": site.active
                }
            }, status=201 if created else 200)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON."}, status=400)
