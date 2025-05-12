from django.urls import path

from file_storage.views import FileListView, DirectoryCreateView, DeleteView, RenameView, \
    FileUploadAjaxView

app_name = 'file_storage'

urlpatterns = [
    path('', FileListView.as_view(), name='list_files'),
    path('create-folder/', DirectoryCreateView.as_view(), name='create_folder'),

    path('upload_ajax/', FileUploadAjaxView.as_view(), name='upload_file_ajax'),
    path('delete/', DeleteView.as_view(), name='delete_item'),
    path('rename/', RenameView.as_view(), name='rename'),
]
