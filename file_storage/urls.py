from django.urls import path

from file_storage.views import HomeView, FileUploadView

app_name = 'file_storage'

urlpatterns = [
    path('', HomeView.as_view(), name='list_files'),
    path('upload/', FileUploadView.as_view(), name='upload_file'),
]
