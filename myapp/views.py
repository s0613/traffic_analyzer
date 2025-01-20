import json

from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status

from myapp.tasks import set_event_mode
from .models import Site
from .forms import AddSiteForm
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.utils.dateparse import parse_datetime
from myapp.ml.rolling_predict import find_best_entry_time
from rest_framework.views import APIView
from django.contrib.auth import authenticate

from django.utils import timezone

@api_view(['POST'])
def best_entry_time_api(request):
    """
    최적 진입 시점 API
    POST 요청 예:
    {
        "site_id": 3,
        "release_time": "2025-01-16T10:00:00"
    }
    """
    site_id = request.data.get('site_id')
    release_time_str = request.data.get('release_time')

    if not site_id or not release_time_str:
        return Response({"error": "필수 파라미터가 누락되었습니다."}, status=400)

    # 현재 시간을 UTC 기준 aware 객체로 가져옴
    current_time = timezone.now()
    release_time = parse_datetime(release_time_str)

    if not release_time:
        return Response({"error": "올바르지 않은 시간 형식입니다."}, status=400)

    # release_time이 naive datetime 객체라면 현재 타임존을 적용하여 aware로 변환
    if timezone.is_naive(release_time):
        release_time = timezone.make_aware(release_time, timezone.get_current_timezone())

    # 서울 시간으로 변환
    current_time_kst = current_time.astimezone(timezone.get_current_timezone())
    release_time_kst = release_time.astimezone(timezone.get_current_timezone())

    # 서울 기준으로 현재 시간과 릴리즈 시간 로그 출력
    print(f"현재 시간 (KST): {current_time_kst.strftime('%H시 %M분')}")
    print(f"릴리즈 시간 (KST): {release_time_kst.strftime('%H시 %M분')}")

    optimal_time = find_best_entry_time(site_id, current_time_kst, release_time_kst)

    if optimal_time:
        formatted_time = optimal_time.strftime("%H시 %M분 %S초")
        return Response({
            "optimal_time": optimal_time.isoformat(),
            "message": f"{formatted_time}에 진입하세요."
        })
    else:
        return Response({
            "optimal_time": None,
            "message": "최적 진입 시간을 찾을 수 없습니다."
        })


def add_site(request):
    """
    새 사이트 추가 폼
    """
    if request.method == "POST":
        form = AddSiteForm(request.POST)
        if form.is_valid():
            domain = form.cleaned_data['domain']
            name = form.cleaned_data['name']
            site_obj, created = Site.objects.get_or_create(domain=domain, defaults={"name": name, "active": True})
            return redirect('site_list')  # 사이트 리스트 페이지로 이동
    else:
        form = AddSiteForm()

    return render(request, 'add_site.html', {"form": form})



def get_sites(request):
    """
    Returns a list of active sites.
    """
    sites = Site.objects.filter(active=True).values("domain", "name")
    return JsonResponse({"sites": list(sites)})

def site_list(request):
    """
    등록된 사이트 목록 표시
    """
    sites = Site.objects.all()
    return render(request, 'site_list.html', {"sites": sites})

def toggle_event_mode(request, site_id):
    """
    특정 사이트의 이벤트 모드를 토글(활성화/비활성화)
    """
    site = get_object_or_404(Site, id=site_id)
    is_active = site.active  # 현재 활성화 상태
    site.active = not is_active
    site.save()

    # Celery 태스크를 호출하여 이벤트 모드 설정
    set_event_mode.delay(site.domain, enable=site.active)

    message = f"{site.domain}의 이벤트 모드가 {'활성화' if site.active else '비활성화'}되었습니다."
    if request.is_ajax():
        return JsonResponse({"message": message, "active": site.active})
    else:
        return redirect('site_list')  # 사이트 리스트 페이지로 리다이렉트

def site_detail(request, site_id):
    """
    사이트 세부 정보 페이지
    - 발매 시간 설정 및 예측 진행 UI 제공
    """
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

class LoginView(APIView):
    def post(self, request, *args, **kwargs):
        email = request.data.get('email')
        password = request.data.get('password')
        user = authenticate(request, username=email, password=password)
        if user:
            return Response({"message": "Login successful"}, status=200)
        return Response({"error": "Invalid credentials"}, status=401)


@method_decorator(csrf_exempt, name='dispatch')
class AddURLView(View):
    def post(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body)
            domain = data.get('domain')
            name = data.get('name', domain)  # 이름이 없으면 도메인을 기본값으로 사용

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