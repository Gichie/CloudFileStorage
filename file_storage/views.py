import urllib

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import Http404
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView

from cloud_file_storage import settings
from file_storage.forms import FileUploadForm, DirectoryCreationForm
from file_storage.mixins import StorageSuccessUrlMixin, UserFormKwargsMixin, ParentInitialMixin
from file_storage.models import UserFile, FileType
from file_storage.utils.minio import get_s3_client, create_empty_directory_marker


class FileListView(LoginRequiredMixin, ListView):
    model = UserFile
    template_name = 'file_storage/list_files.html'
    context_object_name = 'items'

    def get_queryset(self):
        user = self.request.user
        path_param_encoded = self.request.GET.get('path')
        self.current_directory = None
        self.current_path_unencoded = ""

        if path_param_encoded:
            unquoted_path = urllib.parse.unquote_plus(path_param_encoded)
            path_components = [comp for comp in unquoted_path.split('/') if comp and comp not in ['.', '..']]
            self.current_path_unencoded = "/".join(path_components)
            current_parent_obj = None

            if self.current_path_unencoded:
                try:
                    for name_part in path_components:
                        obj = UserFile.objects.get(
                            user=user,
                            name=name_part,
                            parent=current_parent_obj,
                            object_type=FileType.DIRECTORY
                        )
                        current_parent_obj = obj
                    self.current_directory = current_parent_obj
                except UserFile.DoesNotExist:
                    raise Http404("Запрошенная директория не найдена или не является директорией.")
                except UserFile.MultipleObjectsReturned:
                    raise Http404("Ошибка при поиске директории (найдено несколько объектов).")

        if self.current_directory:
            if not self.current_directory.is_directory():
                raise Http404("Указанный путь не является диреторией")
            queryset = UserFile.objects.filter(user=user, parent=self.current_directory)
        else:
            queryset = UserFile.objects.filter(user=user, parent=None)

        return queryset.order_by('object_type', 'name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['current_directory'] = getattr(self, 'current_directory', None)
        context['current_path_unencoded'] = getattr(self, 'current_path_unencoded', '')
        breadcrumbs = []

        if self.current_directory:
            temp_dir = self.current_directory
            path_parts_for_breadcrumbs_url = []

            while temp_dir:
                path_parts_for_breadcrumbs_url.insert(0, temp_dir.name)
                breadcrumbs.insert(0, {
                    'name': temp_dir.name,
                    'url_path_encoded': urllib.parse.quote_plus('/'.join(path_parts_for_breadcrumbs_url))
                })
                temp_dir = temp_dir.parent
        context['breadcrumbs'] = breadcrumbs

        current_folder_id = ''
        if self.current_directory:
            current_folder_id = self.current_directory.id
        context['current_folder_id'] = current_folder_id
        context['parent_id_for_forms'] = current_folder_id
        context['upload_form'] = FileUploadForm(user=self.request.user)

        return context


class FileUploadView(
    LoginRequiredMixin, StorageSuccessUrlMixin,
    UserFormKwargsMixin, CreateView, ParentInitialMixin
):
    model = UserFile
    form_class = FileUploadForm
    template_name = 'file_storage/upload_file.html'
    success_url = reverse_lazy('file_storage:list_files')

    def form_valid(self, form):
        form.instance.user = self.request.user
        try:
            with transaction.atomic():
                response = super().form_valid(form)
                messages.success(self.request, "Файл успешно загружен")
                return response
        except Exception as e:
            messages.error(self.request, f"Ошибка при загрузке файла: {str(e)}")
            return self.form_invalid(form)


class DirectoryCreateView(
    LoginRequiredMixin, StorageSuccessUrlMixin,
    UserFormKwargsMixin, CreateView, ParentInitialMixin
):
    model = UserFile
    form_class = DirectoryCreationForm
    template_name = 'file_storage/create_directory.html'

    def form_valid(self, form):
        form.instance.user = self.request.user
        form.instance.object_type = FileType.DIRECTORY

        try:
            with transaction.atomic():
                response = super().form_valid(form)

                s3_client = get_s3_client()
                key = form.instance.get_s3_key_for_directory_marker()
                create_empty_directory_marker(
                    s3_client,
                    settings.AWS_STORAGE_BUCKET_NAME,
                    key
                )

                messages.success(self.request, "Папка успешно создана")
                return response
        except Exception as e:
            # logger
            messages.error(self.request, f"Ошибка при создании папки: {str(e)}")
            return self.form_invalid(form)


class DeleteView(LoginRequiredMixin, ListView):
    pass


class RenameView(LoginRequiredMixin, ListView):
    pass
