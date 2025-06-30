from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('file_storage.urls', namespace='file_storage')),
    path('users/', include('users.urls', namespace='users')),
    path('__debug__/', include('debug_toolbar.urls')),
]
