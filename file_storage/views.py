import json
import logging
import urllib

from botocore.exceptions import ClientError, ParamValidationError
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db import transaction, IntegrityError
from django.http import JsonResponse, HttpResponseRedirect, StreamingHttpResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import ListView

from cloud_file_storage import settings
from file_storage.exceptions import StorageError, ParentDirectoryNotFoundError, InvalidParentIdError
from file_storage.forms import FileUploadForm, DirectoryCreationForm, RenameItemForm
from file_storage.mixins import QueryParamMixin
from file_storage.models import UserFile, FileType
from file_storage.services import directory_service, upload_service
from file_storage.services.archive_service import ZipStreamGenerator
from file_storage.services.directory_service import DirectoryService
from file_storage.services.upload_service import get_message_and_status
from file_storage.storages.minio import minio_client
from file_storage.utils import ui
from file_storage.utils.path_utils import encode_path_for_url

logger = logging.getLogger(__name__)

FILE_STORAGE_LIST_FILES_URL = 'file_storage:list_files'
FILE_LIST_TEMPLATE = 'file_storage/list_files.html'


class FileListView(QueryParamMixin, LoginRequiredMixin, ListView):
    model = UserFile
    template_name = FILE_LIST_TEMPLATE
    context_object_name = 'items'
    paginate_by = 20

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.user = request.user
        self.current_path_unencoded = request.GET.get('path', '')
        self.current_directory = directory_service.get_current_directory_from_path(
            self.user, self.current_path_unencoded
        )

    def get_queryset(self):
        queryset = UserFile.objects.filter(user=self.user, parent=self.current_directory)
        if not self.current_directory:
            self.current_directory = None
        logger.info(f"User: '{self.user}' has successfully moved to the '{self.current_directory}' directory.")

        return queryset.order_by('object_type', 'name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['current_directory'] = self.current_directory
        context['current_path_unencoded'] = self.current_path_unencoded
        context['breadcrumbs'] = ui.generate_breadcrumbs(self.current_path_unencoded)
        context['DATA_UPLOAD_MAX_NUMBER_FILES'] = settings.DATA_UPLOAD_MAX_NUMBER_FILES
        context['DATA_UPLOAD_MAX_MEMORY_SIZE'] = settings.DATA_UPLOAD_MAX_MEMORY_SIZE

        # Формирование URL для кнопки "Назад"
        context['parent_level_url'] = ui.get_parent_url(
            self.current_path_unencoded, FILE_STORAGE_LIST_FILES_URL
        )

        context['current_folder_id'] = self.current_directory.id if self.current_directory else None

        if 'form_create_folder' not in context:
            context['form_create_folder'] = DirectoryCreationForm(user=self.user)

        return context

    def post(self, request, *args, **kwargs):
        """Обработка создания новой папки"""
        form = DirectoryCreationForm(request.POST, user=request.user)
        if form.is_valid():
            parent_pk = request.POST.get('parent')
            parent_object = None

            if parent_pk:
                parent_object = DirectoryService.get_parent_directory(self.user, parent_pk)

            directory_name = form.cleaned_data['name']

            if UserFile.objects.object_with_name_exists(self.user, directory_name, parent_object):
                logger.warning(
                    f"User {request.user.username}: Directory: {directory_name} "
                    f"already exists in parent '{parent_object.name if parent_object else 'root'}'."
                )
                return JsonResponse({
                    'status': 'error',
                    'message': f"Файл или папка с именем '{directory_name}' уже существует в текущей директории."
                }, status=400)

            result = DirectoryService.create(self.user, directory_name, parent_object)

            if result['success']:
                return JsonResponse({
                    'status': 'success',
                    'message': 'Папка успешно создана!',
                    'directory': {
                        'id': result['directory'].id,
                        'name': result['directory'].name,
                        'type': FileType.DIRECTORY.value,
                        'icon_class': 'bi-folder-fill',
                    }
                })
            return JsonResponse({
                'status': 'error',
                'message': result['message']
            }, status=result['status'])

        else:
            logger.warning(
                f"User '{self.user.username}': Form validation failed. "
                f"Errors: {json.dumps(form.errors.get_json_data(escape_html=False), ensure_ascii=False)}"
            )
            return JsonResponse(
                {'status': 'error', 'message': f'{form.errors["name"][0]}', 'errors': form.errors.as_json()},
                status=400
            )


class FileUploadAjaxView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        relative_paths = request.POST.getlist('relative_paths')
        parent_id = request.POST.get('parent_id')
        files = request.FILES.getlist('files')
        user = request.user

        try:
            parent_object = directory_service.get_parent_directory(user, parent_id)
        except ParentDirectoryNotFoundError:
            # logging внутри
            return JsonResponse(
                {'error': 'Ошибка. Родительская папка не найдена'},
                status=400,
            )
        except InvalidParentIdError:
            # logging внутри
            return JsonResponse(
                {'error': 'Ошибка. Некорректный идентификатор родительской папки.'},
                status=400
            )
        except Exception as e:
            logger.error(f"Unexpected error. User: {user}. {e}")
            return JsonResponse(
                {'error': 'Неизвестная ошибка, попробуйте позже'},
                status=500
            )

        num_files = len(files)

        if relative_paths:
            if num_files != len(relative_paths):
                logger.error(f"{self.__class__.__name__} User: '{user}'. Количество файлов и путей не совпадает.")
                return JsonResponse({'error': 'Данные о путях файлов некорректны.'}, status=400)
        else:
            relative_paths = [None for i in range(num_files)]

        logger.info(
            f"{self.__class__.__name__}: User '{user.username}' ID: {user.id} initiated {num_files} files upload. "
            f"Target parent_id: '{parent_id}'."
        )

        if not files:
            logger.warning(f"User: '{user.username}': File upload request received without files.")
            return JsonResponse({'error': 'Файл отсутствует'}, status=400)

        results = []
        cache = {}
        for uploaded_file, rel_path in zip(files, relative_paths):
            form_data = {'parent': parent_object.pk if parent_object else None}
            form_files = {'file': uploaded_file}
            form = FileUploadForm(form_data, form_files, user=user)

            if form.is_valid():
                try:
                    with transaction.atomic():
                        result, dir_path_cache, parent_object_cache = upload_service.handle_file_upload(
                            uploaded_file, user, parent_object, rel_path, cache
                        )
                    if result and 'error' not in result and dir_path_cache and dir_path_cache not in cache:
                        cache[dir_path_cache] = parent_object_cache

                except Exception as e:
                    result = {
                        'name': uploaded_file.name,
                        'status': 'error',
                        'error': f'Ошибка загрузки файла или папки'
                    }

                if result:
                    results.append(result)

            else:
                error_messages = []
                for field, errors in form.errors.items():
                    error_messages.append(f"{field}: {'; '.join(errors)}")
                error_string = "; ".join(error_messages)
                logger.warning(
                    f"User '{user.username}': File '{uploaded_file.name}' failed validation. "
                    f"Errors: {error_string}"
                )
                results.append({
                    'name': uploaded_file.name,
                    'status': 'error',
                    'error': error_string or 'Ошибка валидации файла.'
                })

        response_data, status_code = get_message_and_status(results)
        logger.info(f"User: '{user}'. {response_data.get('message')}. Status_code: {status_code}")
        return JsonResponse(response_data, status=status_code)


class FileSearchView(QueryParamMixin, LoginRequiredMixin, ListView):
    template_name = 'file_storage/search_results.html'
    paginate_by = 25
    context_object_name = 'search_results'

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.query = self.request.GET.get('query', None)

    def get_queryset(self) -> HttpResponse:
        if not self.query:
            return UserFile.objects.none()

        return UserFile.objects.filter(
            user=self.request.user, name__icontains=self.query
        ).order_by('object_type', 'name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        unencoded_path = self.request.GET.get('current_path_unencoded', '')
        encoded_path = encode_path_for_url(unencoded_path, FILE_STORAGE_LIST_FILES_URL)

        context['query'] = self.query
        context['encoded_path'] = encoded_path

        return context


class DownloadFileView(LoginRequiredMixin, View):
    def get(self, request, file_id):
        unencoded_path = request.GET.get("path_param", "")
        encoded_path = encode_path_for_url(unencoded_path, FILE_STORAGE_LIST_FILES_URL)

        user_file = get_object_or_404(
            UserFile, id=file_id, user=request.user, object_type=FileType.FILE
        )

        s3_key = user_file.file.name

        try:
            if minio_client.check_files_exist((user_file,)):
                presigned_url = minio_client.s3_client.generate_presigned_url(
                    'get_object',
                    Params={
                        'Bucket': settings.AWS_STORAGE_BUCKET_NAME,
                        'Key': s3_key,
                        'ResponseContentDisposition': f'attachment; filename="{user_file.name}"'
                    },
                    ExpiresIn=1800
                )
                logger.info(f"File downloaded successfully. s3_key: {s3_key}, presigned_url: {presigned_url}")
                return HttpResponseRedirect(presigned_url)

            else:
                logger.warning(f"User: '{user_file.user}. File does not found in s3/minio storage'",
                               exc_info=True)
                messages.warning(request, f"Такого файла: '{user_file}' не существует")

        except ClientError as e:
            logger.error(f"Error generating presigned URL for s3_key: {s3_key}: {e}")
            messages.error(request, "Произошла ошибка при обращении к хранилищу, попробуйте позже")
        except ParamValidationError as e:
            logger.error(f"{e}")
            messages.error(request, "Произошла ошибка при запросе к хранилищу")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            messages.error(request, "Произошла ошибка при скачивании файла, попробуйте позже")

        return redirect(encoded_path)


class DownloadDirectoryView(LoginRequiredMixin, View):
    def get(self, request, directory_id):
        unencoded_path = request.GET.get("path_param", "")
        encoded_path = encode_path_for_url(unencoded_path, FILE_STORAGE_LIST_FILES_URL)

        user = request.user
        directory = get_object_or_404(
            UserFile, id=directory_id, user=user, object_type=FileType.DIRECTORY
        )

        all_files = UserFile.objects.get_all_children_files(directory)

        if not minio_client.check_files_exist(all_files):
            messages.error(request, "Не удалось прочитать некоторые файлы из хранилища")
            return redirect(FILE_STORAGE_LIST_FILES_URL)

        zip_generator = ZipStreamGenerator(directory, all_files)

        zip_filename = f"{directory.name}.zip"
        encoded_zip_filename = urllib.parse.quote(zip_filename)

        try:
            response = StreamingHttpResponse(
                zip_generator.generate(), content_type='application/zip'
            )
        except StorageError as e:
            # Логирование внутри _check_files_exist
            messages.error(request, "Не удалось прочитать некоторые файлы из хранилища")
            return redirect(encoded_path)
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            messages.error(request, 'Произошла ошибка при скачивании архива')
            return redirect(encoded_path)

        response['Content-Disposition'] = f'attachment; filename="{encoded_zip_filename}"'
        response['Cache-Control'] = 'no-cache'

        logger.info(f"User '{request.user.username}' started "
                    f"downloading directory '{directory.name}' "
                    f"as '{zip_filename}'.")
        return response


class DeleteView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        user = request.user

        unencoded_path = request.POST.get("unencoded_path", "")
        encoded_path = encode_path_for_url(unencoded_path, FILE_STORAGE_LIST_FILES_URL)

        item_id = request.POST.get('item_id')

        try:
            storage_object = get_object_or_404(UserFile, user=user, id=item_id)
            DirectoryService.delete_obj(storage_object)
            messages.success(request, f"{storage_object.get_object_type_display()} успешно удален(а)!")
        except ValidationError as e:
            logger.warning(
                f"User '{user}'. Invalid type received. UUID required. {type(item_id)} received.",
                exc_info=True
            )
            messages.warning(request, "Удалить объект не удалось. Неправильный ID объекта")
        except StorageError as e:
            logger.error(f"User '{user}'. Error while deleting '{storage_object}' from s3. {e}", exc_info=True)
            messages.error(request, "Удалить объект не получилось.")

        return redirect(encoded_path)


class RenameView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        unencoded_path = request.POST.get("unencoded_path", "")
        item_id = request.POST.get('id')
        user = request.user
        new_name = request.POST.get('name')

        encoded_path = encode_path_for_url(unencoded_path, FILE_STORAGE_LIST_FILES_URL)

        if not item_id:
            logger.warning(f"User '{user}'. Object ID was not transmitted")
            messages.error(request, "Не удалось определить объект для переименования (ID отсутствует).")
            return redirect(encoded_path)

        try:
            object_instance = get_object_or_404(UserFile, user=user, id=item_id)
        except ValidationError as e:
            logger.warning(
                f"User '{user}'. Invalid type received. UUID required. {type(item_id)} received. {e}",
                exc_info=True
            )
            messages.warning(request, "Переименовать объект не удалось. Неправильный ID объекта")
            return redirect(encoded_path)

        if UserFile.objects.object_with_name_exists(user, new_name, object_instance.parent):
            logger.warning(f"User '{user}' tried to save an object with an existing one.")
            messages.warning(request, "Файл или папка с таким именем уже существует")
            return redirect(encoded_path)

        form = RenameItemForm(request.POST, instance=object_instance)
        if form.is_valid():
            try:
                with transaction.atomic():
                    if object_instance.object_type == FileType.FILE:
                        old_minio_key = object_instance.file.name
                    else:
                        old_minio_key = object_instance.path

                    form.save()
                    new_minio_key = object_instance.get_full_path()

                    if object_instance.object_type == FileType.FILE:
                        minio_client.rename_file(old_minio_key, new_minio_key)

                    elif object_instance.object_type == FileType.DIRECTORY:
                        if old_minio_key and new_minio_key and old_minio_key != new_minio_key:
                            DirectoryService.update_children_paths(
                                object_instance, old_minio_key, new_minio_key
                            )
                        minio_client.rename_directory(old_minio_key, new_minio_key)

                    logger.info(f"User '{user}' renamed {object_instance.object_type} "
                                f"to '{form.cleaned_data['name']}'")
                    messages.success(request,
                                     f"{object_instance.get_object_type_display()} успешно переименован(а)")

            except IntegrityError as e:
                logger.warning(f"User: '{user}'. Error while renaming object. '{object_instance.object_type}' "
                               f"with that name already exists with ID {object_instance.id}.\n{e}. ", exc_info=True)
                messages.warning(request,
                                 f"{object_instance.get_object_type_display()} с таким именем уже существует")
            except StorageError as e:
                logger.error(f"User '{user}'. Error getting s3/minio keys. {e}", exc_info=True)
                messages.error(request, "Переименовать объект не получилось. "
                                        "Не удалось получить ключи для удаления из хранилища")
            except Exception as e:
                logger.warning(f"User: '{user}'. Error while renaming '{object_instance.object_type}'"
                               f"with ID {object_instance.id}.\n{e}", exc_info=True)
                messages.error(request, f"Произошла ошибка при переименовании")

        else:
            messages.warning(request, form.errors["name"][0])

        return redirect(encoded_path)
