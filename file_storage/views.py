import urllib

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import Http404, JsonResponse
from django.urls import reverse_lazy, reverse
from django.views import View
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
            queryset = UserFile.objects.filter(user=user, parent=self.current_directory)
        else:
            queryset = UserFile.objects.filter(user=user, parent=None)

        return queryset.order_by('object_type', 'name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['current_directory'] = getattr(self, 'current_directory', None)
        context['current_path_unencoded'] = getattr(self, 'current_path_unencoded', '')
        breadcrumbs = []
        parent_level_url = None
        current_folder_id = None

        if self.current_directory:
            temp_dir = self.current_directory
            path_parts_for_breadcrumbs_url = self.current_path_unencoded.split('/')

            while temp_dir:

                breadcrumbs.insert(0, {
                    'name': temp_dir.name,
                    'url_path_encoded': urllib.parse.quote_plus('/'.join(path_parts_for_breadcrumbs_url))
                })
                path_parts_for_breadcrumbs_url.pop()
                temp_dir = temp_dir.parent


            # Формирование URl для кнопки "Назад"
            if self.current_directory.parent:
                parent_path_encoded = self.current_directory.parent.get_path_for_url()
                parent_level_url = f"{reverse('file_storage:list_files')}?path={parent_path_encoded}"
            else:
                parent_level_url = reverse('file_storage:list_files')

            current_folder_id = self.current_directory.id

        context['parent_level_url'] = parent_level_url
        context['breadcrumbs'] = breadcrumbs
        context['current_folder_id'] = current_folder_id

        return context


class FileUploadAjaxView(LoginRequiredMixin, View):

    def _handle_file_upload(self, uploaded_file, user, parent_object):
        """
        Обрабатывает один загруженный файл: проверяет, создает UserFile, загружает файл в Minio через FileField.
        Возвращает словарь с результатом.
        """

        uploaded_file_name = uploaded_file.name

        if UserFile.objects.filter(
                user=user,
                parent=parent_object,
                name=uploaded_file_name
        ).exists():
            # todo logging
            return {
                'name': uploaded_file_name,
                'status': 'error',
                'error': 'Файл или папка с таким именем уже существует.'
            }

        try:
            with transaction.atomic():
                user_file_instance = UserFile(
                    user=user,
                    file=uploaded_file,
                    name=uploaded_file_name,
                    parent=parent_object,
                    object_type=FileType.FILE,
                )
                user_file_instance.save()
                # todo logging

                return {
                    'name': user_file_instance.name,
                    'status': 'success',
                    'id': str(user_file_instance.id)
                }

        except Exception as e:
            # todo logging
            return {
                'name': uploaded_file_name,
                'status': 'error',
                'error': 'Ошибка при загрузке файла в хранилище'
            }

    def post(self, request, *args, **kwargs):
        files = request.FILES.getlist('files')
        parent_id = request.POST.get('parent_id')
        user = request.user
        parent_object = None

        if parent_id:
            try:
                parent_object = UserFile.objects.get(
                    id=parent_id,
                    user=user,
                    object_type=FileType.DIRECTORY
                )
            except UserFile.DoesNotExist:
                # todo logging
                return JsonResponse(
                    data={'error': 'Родительская папка не найдена или не является директорией.'},
                    status=400,
                )
            except UserFile.MultipleObjectsReturned:
                # todo logging
                return JsonResponse(
                    data={'error': 'Найдено несколько родительских папок с одинаковым названием'},
                    status=500,
                )
            except Exception as e:
                # todo logging
                return JsonResponse(
                    data={'error': 'Ошибка на стороне сервера'},
                    status=500,
                )

        if not files:
            return JsonResponse({'error': 'Файлы не педоставлены'}, status=400)

        results = []
        for uploaded_file in files:
            form_data = {'parent': parent_object.pk if parent_object else None}
            form_files = {'file': uploaded_file}
            form = FileUploadForm(form_data, form_files, user=user)

            if form.is_valid():
                try:
                    result = self._handle_file_upload(uploaded_file, user, parent_object)
                    results.append(result)
                except Exception as e:
                    # logger.error(
                    #     f"Critical error processing {uploaded_file.name} (user: {user.username}): {e}",
                    #     exc_info=True
                    # )
                    results.append({
                        'name': uploaded_file.name,
                        'status': 'error',
                        'error': 'Внутренняя ошибка сервера при загрузке файла',
                    })
            else:
                error_messages = []
                for field, errors in form.errors.items():
                    error_messages.append(f"{field}: {'; '.join(errors)}")
                error_string = "; ".join(error_messages)
                # todo logging
                results.append({
                    'name': uploaded_file.name,
                    'status': 'error',
                    'error': error_string or 'Ошибка валидации файла.'
                })

        any_errors = any(res['status'] == 'error' for res in results)

        if any_errors:
            if all(res['status'] == 'error' for res in results):
                message = 'Файл не удалось загрузить.'
            else:
                message = 'Некоторые файлы были загружены с ошибкой.'
        else:
            message = 'Все файлы успешно загружены.'

        http_status = 200
        if any_errors:
            http_status = 207

        return JsonResponse({'message': message, 'results': results}, status=http_status)


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
