from django.urls import path

from file_storage.views import FileListView, DeleteView, RenameView, \
    FileUploadAjaxView, DownloadFileView

app_name = 'file_storage'

urlpatterns = [
    path('', FileListView.as_view(), name='list_files'),
    path('upload_ajax/', FileUploadAjaxView.as_view(), name='upload_file_ajax'),
    path('delete/', DeleteView.as_view(), name='delete_item'),
    path('rename/', RenameView.as_view(), name='rename'),
    path('download/file/<uuid:file_id>', DownloadFileView.as_view(), name='download_file')
]
