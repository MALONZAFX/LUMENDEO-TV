# myapp/urls.py - FIXED VERSION
from django.urls import path
from django.views.generic import RedirectView
from . import views

urlpatterns = [
    # Public URLs
    path('', views.home, name='home'),
    path('movie/', views.movie_view, name='movie_view'),
    
    # Payment URLs - ONLY ONE mpesa-checkout endpoint
    path('mpesa-checkout/', views.mpesa_checkout, name='mpesa_checkout'),
    path('check-payment-status/', views.check_payment_status, name='check_payment_status'),
    

    
    # Test URLs
   
    # Dashboard URLs
    path('dashboard/', views.all_in_one_dashboard, name='dashboard_home'),
    path('dashboard/login/', views.dashboard_login, name='dashboard_login'),
    path('dashboard/logout/', views.admin_logout, name='admin_logout'),
    
    # AJAX URLs
    path('dashboard/ajax/upload-video/', views.ajax_upload_video, name='ajax_upload_video'),
    path('dashboard/ajax/save-settings/', views.ajax_save_settings, name='ajax_save_settings'),
    path('dashboard/ajax/video/<int:video_id>/delete/', views.ajax_delete_video, name='ajax_delete_video'),
    path('dashboard/ajax/video/<int:video_id>/update/', views.ajax_update_video, name='ajax_update_video'),
    
    # API URLs
    path('dashboard/api/user/<str:user_id>/', views.api_user_details, name='api_user_details'),
    path('dashboard/api/payment/<int:payment_id>/', views.api_payment_details, name='api_payment_details'),
    path('dashboard/api/video/<int:video_id>/', views.api_video_details, name='api_video_details'),
    path('dashboard/live-data/', views.dashboard_live_data, name='dashboard_live_data'),
    
    # Debug URLs
    path('dashboard/debug/videos/', views.debug_videos, name='debug_videos'),
    path('dashboard/debug/database/', views.debug_database, name='debug_database'),
    
    # Compatibility URLs
    path('dashboard/simple/', views.dashboard_simple, name='dashboard_simple'),
    path('dashboard/content/create/', views.content_create_simple, name='content_create'),
    path('dashboard/users/list/', views.users_list_simple, name='users_list'),
    path('dashboard/settings/view/', views.settings_view_simple, name='settings_view'),

    # Fix missing favicon
    path('favicon.ico', RedirectView.as_view(url='/static/img/favicon.ico', permanent=True)),
]