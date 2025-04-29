from django.urls import path

from file_storage.views import HomeView, upload_file, test_minio_connection

app_name = 'file_storage'

urlpatterns = [
    path('', HomeView.as_view(), name='list_files'),
    path('upload/', upload_file, name='upload_file'),
]
