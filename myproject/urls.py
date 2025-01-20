from django.contrib import admin
from django.urls import path
from myapp.views import add_site, site_list
from myapp.views import best_entry_time_api
from myapp.views import site_list, add_site, toggle_event_mode
from myapp.views import get_sites, LoginView, AddURLView
urlpatterns = [
    path('admin/', admin.site.urls),
    path('sites/', site_list, name='site_list'),
    path('sites/add/', add_site, name='add_site'),
    path('api/sites/', get_sites, name='get_sites'),
    path('api/best_entry_time/', best_entry_time_api, name='best_entry_time'),
    path('sites/<int:site_id>/toggle_event/', toggle_event_mode, name='toggle_event_mode'),
    path('api/login/', LoginView.as_view(), name='login'),
    path('api/add_url/', AddURLView.as_view(), name='add_url'),
]