# dict/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # Django Admin (Optional - keep if you need it)
    # path('django-admin/', admin.site.urls),  # Optional: Django admin at different URL
    
    # Your custom dashboard and website routes
    path('', include('myapp.urls')),

    
]

# Add static files serving in development
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)