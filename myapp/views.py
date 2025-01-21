#views.py
import json
import threading

from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from django.contrib.auth import authenticate
from tasks import set_event_mode, deactivate_fast_mode
from .models import Site
from .forms import AddSiteForm
from myapp.ml.rolling_predict import find_best_entry_time
from rest_framework.views import APIView
from django.core.cache import cache
@api_view(['POST'])
def best_entry_time_api(request):
    site_id = request.data.get('site_id')
    release_time_str = request.data.get('release_time')

    if not site_id or not release_time_str:
        return Response({"error": "필수 파라미터가 누락되었습니다."}, status=400)

    # 현재 시간을 UTC 기준 aware 객체로 가져옴
    current_time = timezone.now()
    release_time = parse_datetime(release_time_str)

    if not release_time:
        return Response({"error": "올바르지 않은 시간 형식입니다."}, status=400)

    if timezone.is_naive(release_time):
        release_time = timezone.make_aware(release_time, timezone.get_current_timezone())

    # 서울 시간으로 변환
    current_time_kst = current_time.astimezone(timezone.get_current_timezone())
    release_time_kst = release_time.astimezone(timezone.get_current_timezone())

    # 빠른 모드 중복 체크
    if cache.get(f"fast_mode_{site_id}"):
        return Response({"message": "현재 빠른 모드가 활성화되어 있습니다. 잠시 후 다시 시도해주세요."}, status=400)

    optimal_time = find_best_entry_time(site_id, current_time_kst, release_time_kst)

    if optimal_time:
        formatted_time = optimal_time.strftime("%H시 %M분 %S초")

        # Redis에 빠른 모드 활성화 (1분)
        cache.set(f"fast_mode_{site_id}", True, timeout=60)

        # 비동기 태스크 호출
        set_event_mode.delay(site_id, enable=True)

        # 타이머를 설정하여 10초 후 자동으로 일반 모드로 전환
        threading.Timer(10.0, deactivate_fast_mode, args=[site_id]).start()

        return Response({
            "optimal_time": optimal_time.isoformat(),
            "message": f"{formatted_time}에 진입하세요."
        })
    else:
        return Response({
            "optimal_time": None,
            "message": "최적 진입 시간을 찾을 수 없습니다."
        })
# 새 사이트 추가 폼
def add_site(request):
    if request.method == "POST":
        form = AddSiteForm(request.POST)
        if form.is_valid():
            domain = form.cleaned_data['domain']
            name = form.cleaned_data['name']
            site_obj, created = Site.objects.get_or_create(domain=domain, defaults={"name": name, "active": True})
            return redirect('site_list')
    else:
        form = AddSiteForm()

    return render(request, 'add_site.html', {"form": form})

# 사이트 목록 가져오기
def get_sites(request):
    sites = Site.objects.filter(active=True).values("domain", "name")
    return JsonResponse({"sites": list(sites)})

# 사이트 리스트 페이지
def site_list(request):
    sites = Site.objects.all()
    return render(request, 'site_list.html', {"sites": sites})

# 이벤트 모드 토글
def toggle_event_mode(request, site_id):
    site = get_object_or_404(Site, id=site_id)
    is_active = site.active
    site.active = not is_active
    site.save()

    # 비동기 태스크 호출
    set_event_mode.delay(site.domain, enable=site.active)

    message = f"{site.domain}의 이벤트 모드가 {'활성화' if site.active else '비활성화'}되었습니다."
    if request.is_ajax():
        return JsonResponse({"message": message, "active": site.active})
    else:
        return redirect('site_list')

# 사이트 세부 정보 페이지
def site_detail(request, site_id):
    site = get_object_or_404(Site, id=site_id)

    if request.method == "POST":
        release_time_str = request.POST.get("release_time")
        current_time_str = request.POST.get("current_time")
        if release_time_str and current_time_str:
            release_time = parse_datetime(release_time_str)
            current_time = parse_datetime(current_time_str)

            # 이벤트 모드 활성화
            set_event_mode.delay(site.domain, enable=True)

            # 최적 진입 시간 예측
            optimal_time = find_best_entry_time(site_id, current_time, release_time)
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

# 로그인 API
class LoginView(APIView):
    def post(self, request, *args, **kwargs):
        email = request.data.get('email')
        password = request.data.get('password')
        user = authenticate(request, username=email, password=password)
        if user:
            return Response({"message": "Login successful"}, status=200)
        return Response({"error": "Invalid credentials"}, status=401)

# URL 추가 API
@method_decorator(csrf_exempt, name='dispatch')
class AddURLView(View):
    def post(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body)
            domain = data.get('domain')
            name = data.get('name', domain)

            if not domain:
                return JsonResponse({"error": "Domain is required."}, status=400)

            # URL에서 `https://` 제거 및 `.`을 `_`로 변환
            sanitized_domain = domain.replace("https://", "").replace(".", "_")

            site, created = Site.objects.get_or_create(
                domain=sanitized_domain,
                defaults={"name": name, "active": True}
            )
            return JsonResponse({
                "message": "URL added successfully.",
                "site": {"id": site.id, "domain": site.domain, "name": site.name, "active": site.active}
            }, status=201 if created else 200)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON."}, status=400)
