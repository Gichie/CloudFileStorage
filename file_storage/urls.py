from django.urls import path

from file_storage.views import FileListView, DeleteView, RenameView, \
    FileUploadAjaxView, DownloadFileView, DownloadDirectoryView, FileSearchView

app_name = 'file_storage'

urlpatterns = [
    path('', FileListView.as_view(), name='list_files'),
    path('upload_ajax/', FileUploadAjaxView.as_view(), name='upload_file_ajax'),
    path('download/file/<uuid:file_id>', DownloadFileView.as_view(), name='download_file'),
    path('download/directory/<uuid:directory_id>', DownloadDirectoryView.as_view(), name='download_directory'),
    path('search/', FileSearchView.as_view(), name='search_files'),
    path('delete/', DeleteView.as_view(), name='delete_item'),
    path('rename/', RenameView.as_view(), name='rename'),
]
