from django.urls import path

from file_storage.views import FileListView, FileUploadView, DirectoryCreateView, DeleteView, RenameView

app_name = 'file_storage'

urlpatterns = [
    path('', FileListView.as_view(), name='list_files'),
    path('upload/', FileUploadView.as_view(), name='upload_file'),
    path('create-folder/', DirectoryCreateView.as_view(), name='create_directory'),

    path('delete/<uuid:pk>', DeleteView.as_view(), name='delete_item'),
    path('rename/<uuid:pk>', RenameView.as_view(), name='rename_item'),
]
