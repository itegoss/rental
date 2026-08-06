"""
URL configuration for rental project.
"""
from app.views import service_worker
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic.base import RedirectView
from django.templatetags.static import static as static_url

urlpatterns = [
    path('admin/', admin.site.urls),

    path(
        'favicon.ico',
        RedirectView.as_view(
            url=settings.STATIC_URL + 'images/favicon.ico',
            permanent=True
        ),
    ),

    # Service Worker
   path(
    "service-worker.js",
    service_worker,
    name="service_worker",
),

    # App URLs
    path('', include('app.urls')),

    # Social Auth
    path('auth/', include('social_django.urls', namespace='social')),
]

if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT
    )