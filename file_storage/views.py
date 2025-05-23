import json
import logging
import urllib

from botocore.exceptions import NoCredentialsError, BotoCoreError, ClientError, ParamValidationError
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import SuspiciousFileOperation
from django.db import transaction, IntegrityError
from django.http import Http404, JsonResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views import View
from django.views.generic import ListView

from cloud_file_storage import settings
from file_storage.exceptions import NameConflictError
from file_storage.forms import FileUploadForm, DirectoryCreationForm
from file_storage.models import UserFile, FileType
from file_storage.utils.minio import get_s3_client, create_empty_directory_marker

logger = logging.getLogger(__name__)


class FileListView(LoginRequiredMixin, ListView):
    model = UserFile
    template_name = 'file_storage/list_files.html'
    context_object_name = 'items'

    def get_queryset(self):
        user = self.request.user
        path_param_encoded = self.request.GET.get('path')
        self.current_directory = None
        self.current_path_unencoded = ""

        logger.info(
            f"User '{user.username}' ID: {user.id} requested file list. "
            f"Raw path_param: '{path_param_encoded}'"
        )

        if path_param_encoded:
            unquoted_path = urllib.parse.unquote(path_param_encoded)
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
                    logger.error(
                        f"User '{user.username}': Directory not found for path component '{name_part}' "
                        f"Full requested path: '{self.current_path_unencoded}'. Raising Http404."
                    )
                    raise Http404("Запрошенная директория не найдена или не является директорией.")
                except UserFile.MultipleObjectsReturned:
                    logger.error(
                        f"User '{user.username}': Multiple objects returned for path component '{name_part}' "
                        f"Full requested path: '{self.current_path_unencoded}'. This indicates a data integrity issue. Raising Http404."
                    )
                    raise Http404("Ошибка при поиске директории (найдено несколько объектов).")

        if self.current_directory:
            queryset = UserFile.objects.filter(user=user, parent=self.current_directory)
            logger.info(f"User '{user.username}': Successfully resolved path '{self.current_path_unencoded}'")
        else:
            queryset = UserFile.objects.filter(user=user, parent=None)
            logger.info(
                f"User '{user.username}': Listing root directory contents (no specific path or path resolved to root)."
            )

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

        if 'form_create_folder' not in context:
            context['form_create_folder'] = DirectoryCreationForm(user=self.request.user)

        return context

    def post(self, request, *args, **kwargs):
        form = DirectoryCreationForm(request.POST, user=request.user)
        if form.is_valid():
            parent_pk = request.POST.get('parent')
            parent_object = None

            if parent_pk:
                try:
                    parent_object = UserFile.objects.get(
                        pk=parent_pk,
                        user=self.request.user,
                        object_type=FileType.DIRECTORY,
                    )

                    logger.info(
                        f"[{self.__class__.__name__}] User '{self.request.user.username}' "
                        f"successfully identified parent directory: '{parent_object.name}' (ID: {parent_object.id}) "
                        f"for new directory creation."
                    )

                except UserFile.DoesNotExist:
                    logger.warning(
                        f"Parent directory not found. pk={parent_pk} user={self.request.user.username} ID: {self.request.user.id} "
                        f"Requested parent_pk: '{parent_pk}'. Query was for object_type: {FileType.DIRECTORY}"
                    )
                    return JsonResponse(
                        {'status': 'error', 'message': 'Родительская папка не найдена'},
                        status=400,
                    )

                except (ValueError, TypeError):
                    logger.error(
                        f"User={self.request.user.username} ID: {self.request.user.id} "
                        f"object_type={FileType.DIRECTORY} Invalid parent folder identifier. pk={parent_pk}",
                        exc_info=True
                    )
                    return JsonResponse(
                        {'status': 'error', 'message': 'Некорректный идентификатор родительской папки.'},
                        status=400
                    )

            directory_name = form.cleaned_data['name']
            if UserFile.objects.filter(
                    user=request.user,
                    name=directory_name,
                    parent=parent_object,
            ).exists():
                logger.warning(
                    f"User {request.user.username}: Directory: {directory_name} "
                    f"already exists in parent '{parent_object.name if parent_object else 'root'}'."
                )
                return JsonResponse({
                    'status': 'error',
                    'message': f"Файл или папка с именем '{directory_name}' уже существует в текущей директории."
                }, status=400)

            new_directory = form.save(commit=False)
            new_directory.user = self.request.user
            new_directory.object_type = FileType.DIRECTORY
            new_directory.parent = parent_object

            try:
                with transaction.atomic():
                    new_directory.save()
                    s3_client = get_s3_client()
                    key = new_directory.get_s3_key_for_directory_marker()
                    create_empty_directory_marker(
                        s3_client,
                        settings.AWS_STORAGE_BUCKET_NAME,
                        key
                    )

                    logger.info(
                        f"User {self.request.user.username} Directory successfully created in DB and S3. "
                        f"Path={key}, DB ID={new_directory.id}"
                    )

                    return JsonResponse({
                        'status': 'success',
                        'message': 'Папка успешно создана!',
                        'directory': {
                            'id': new_directory.id,
                            'name': new_directory.name,
                            'type': FileType.DIRECTORY.value,
                            'icon_class': 'bi-folder-fill',
                        }
                    })

            except IntegrityError as e:
                logger.error(f"Database integrity error during folder creation: {e}", exc_info=True)
                return JsonResponse({
                    'status': 'error',
                    'message': 'Ошибка базы данных: Не удалось создать папку из-за конфликта данных.'
                }, status=409)

            except NoCredentialsError:
                logger.critical("S3/Minio credentials not found. Cannot create directory marker.", exc_info=True)
                return JsonResponse({
                    'status': 'error',
                    'message': 'Ошибка конфигурации сервера: Не удалось подключиться к хранилищу файлов.'
                }, status=500)

            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code")
                logger.error(f"S3 ClientError while creating directory marker '{key}': {e} (Code: {error_code})",
                             exc_info=True)
                return JsonResponse({
                    'status': 'error',
                    'message': 'Ошибка хранилища. Не удалось создать папку в облаке.'
                }, status=500)

            except BotoCoreError as e:
                logger.error(f"BotoCoreError while creating directory marker '{key}': {e}", exc_info=True)
                return JsonResponse({
                    'status': 'error',
                    'message': 'Произошла ошибка при взаимодействии с файловым хранилищем. Попробуйте позже.'
                }, status=503)

            except AttributeError as e:
                logger.error(
                    f"AttributeError, possibly related to form.instance or S3 key generation: {e}", exc_info=True
                )
                return JsonResponse({
                    'status': 'error',
                    'message': 'Внутренняя ошибка сервера при подготовке данных для хранилища.'
                }, status=500)

            except Exception as e:
                logger.critical(f"Unexpected error during folder creation (S3 part): {e}", exc_info=True)
                return JsonResponse({
                    'status': 'error',
                    'message': 'Произошла непредвиденная ошибка при создании папки.'
                }, status=500)
        else:
            logger.warning(
                f"User '{self.request.user.username}': Form validation failed. Errors: {json.dumps(form.errors.get_json_data(escape_html=False), ensure_ascii=False)}"
            )
            return JsonResponse(
                {'status': 'error', 'message': f'{form.errors["name"][0]}', 'errors': form.errors.as_json()},
                status=400
            )


class FileUploadAjaxView(LoginRequiredMixin, View):
    def create_directories_from_path(self, user, parent_object, path_components):
        current_parent = parent_object

        for directory_name in path_components:
            if UserFile.objects.filter(
                user=user,
                name=directory_name,
                parent=current_parent,
                object_type=FileType.FILE
            ).exists():
                message = (f"Upload failed. File with this name already exists. User: {user}. "
                          f"Name: {directory_name}, parent: {current_parent}")
                logger.warning(message)
                raise NameConflictError(message, directory_name, current_parent)

            directory_object, created = UserFile.objects.get_or_create(
                user=user,
                name=directory_name,
                parent=current_parent,
                object_type=FileType.DIRECTORY,
            )

            if created:
                logger.info(
                    f"User '{user.username}': Created directory '{directory_name}' "
                    f"(ID: {directory_object.id}) under parent "
                    f"'{current_parent.name if current_parent else 'root'}'."
                )
                try:
                    # Создание "директории" в S3/Minio
                    s3_client = get_s3_client()
                    key = directory_object.get_s3_key_for_directory_marker()
                    create_empty_directory_marker(
                        s3_client,
                        settings.AWS_STORAGE_BUCKET_NAME,
                        key
                    )
                    logger.info(f"User '{user.username}': S3 marker created for directory '{key}'.")
                except (NoCredentialsError, ClientError, BotoCoreError) as e:
                    logger.error(
                        f"User '{user.username}': FAILED to create S3 marker for directory '{directory_object.name}' "
                        f"(ID: {directory_object.id}). Error: {e}",
                        exc_info=True
                    )
                    raise Exception(f"Ошибка создания папки {directory_name} в S3 хранилище.") from e

            current_parent = directory_object
        return current_parent

    def _handle_file_upload(self, uploaded_file, user, parent_object, relative_path):
        """
        Обрабатывает один загруженный файл: проверяет, создает UserFile, загружает файл в Minio через FileField.
        Возвращает словарь с результатом.
        """

        uploaded_file_name = uploaded_file.name

        log_prefix = (f"User '{user.username}' (ID: {user.id}), File '{uploaded_file_name}', "
                      f"Parent ID: {parent_object.id if parent_object else 'None'}, relative_path: {relative_path}")

        if relative_path:
            path_components = [component for component in relative_path.split('/') if component]

            if not path_components:
                logger.warning(f"Invalid relative path {log_prefix}")
                return {
                    'name': uploaded_file_name,
                    'status': 'error',
                    'error': f'Некорректный относительный путь {relative_path}'
                }

            directory_path_parts = path_components[:-1]

            try:
                if directory_path_parts:
                    with transaction.atomic():
                        parent_object = self.create_directories_from_path(user, parent_object, directory_path_parts)

            except NameConflictError as e:
                return {
                    'name': e.name,
                    'status': 'error',
                    'error': e.get_message(),
                    'relative_path': relative_path
                }

            except Exception as e:
                logger.error(
                    f"Failed to create directory structure for '{relative_path}'. User: {user.username}. Error: {e}",
                    exc_info=True
                )
                return {
                    'name': uploaded_file_name,
                    'status': 'error',
                    'error': f'Ошибка при создании структуры папок',
                    'relative_path': relative_path
                }

        if UserFile.objects.filter(
                user=user,
                parent=parent_object,
                name=uploaded_file_name,
        ).exists():
            message = f"Upload failed. File or directory with this name already exists. {log_prefix}"
            logger.warning(message)
            raise NameConflictError(message, uploaded_file_name, parent_object)

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

                logger.info(
                    f"{log_prefix} Successfully uploaded and saved. "
                    f"UserFile ID: {user_file_instance.id}, Minio Path: {user_file_instance.file.name}"
                )

                return {
                    'name': user_file_instance.name,
                    'status': 'success',
                    'id': str(user_file_instance.id)
                }

        except SuspiciousFileOperation as e:
            logger.warning(f"Loading error: path too long {log_prefix}: {e}", exc_info=True)
            return {
                'name': uploaded_file_name,
                'status': 'error',
                'error': 'Ошибка при загрузке файла: слишком длинный путь для файла'
            }
        except Exception as e:
            logger.error(
                f"{log_prefix} Error during file save or Minio upload: {e}",
                exc_info=True
            )
            return {
                'name': uploaded_file_name,
                'status': 'error',
                'error': 'Ошибка при загрузке файла в хранилище'
            }

    def post(self, request, *args, **kwargs):
        files = request.FILES.getlist('files') or request.FILES.getlist('file')
        relative_path = request.POST.get('relative_path')
        parent_id = request.POST.get('parent_id')
        parent_object = None
        user = request.user

        # todo адаптировать логи под загрузку папки
        logger.info(
            f"{self.__class__.__name__}: User '{user.username}' ID: {user.id} initiated file upload. "
            f"Number of files: {len(files)}. Target parent_id: '{parent_id}'."
        )

        if not files:
            logger.warning(f"User '{user.username}': File upload request received without files.")
            return JsonResponse({'error': 'Файл отсутствует'}, status=400)

        if parent_id:
            try:
                parent_object = UserFile.objects.get(
                    id=parent_id,
                    user=user,
                    object_type=FileType.DIRECTORY
                )
            except UserFile.DoesNotExist:
                logger.warning(
                    f"User '{user.username}': Attempted to upload to non-existent or unauthorized parent directory ID '{parent_id}'."
                )
                return JsonResponse(
                    data={'error': 'Родительская папка не найдена или не является директорией.'},
                    status=400,
                )
            except UserFile.MultipleObjectsReturned:
                logger.error(
                    f"User '{user.username}': Multiple parent directories found for ID '{parent_id}'. Data integrity issue."
                )
                return JsonResponse(
                    data={'error': 'Найдено несколько родительских папок с одинаковым названием'},
                    status=500,
                )
            except (ValueError, TypeError):
                logger.warning(
                    f"User '{user.username}': Invalid base parent directory ID '{parent_id}'."
                )
                return JsonResponse(
                    data={'error': 'Некорректный ID родительской папки.'},
                    status=400,
                )
            except Exception as e:
                logger.error(
                    f"User '{user.username}': Unexpected error finding parent directory ID '{parent_id}': {e}.",
                    exc_info=True
                )
                return JsonResponse(
                    data={'error': 'Ошибка на стороне сервера'},
                    status=500,
                )

        results = []
        for uploaded_file in files:
            form_data = {'parent': parent_object.pk if parent_object else None}
            form_files = {'file': uploaded_file}
            form = FileUploadForm(form_data, form_files, user=user)

            if form.is_valid():
                try:
                    result = self._handle_file_upload(uploaded_file, user, parent_object, relative_path)
                    results.append(result)
                except NameConflictError as e:
                    results.append({
                        'name': e.name,
                        'status': 'error',
                        'error': e.get_message(),
                    })
                except Exception as e:
                    logger.critical(
                        f"User '{user.username}': Critical unhandled error in _handle_file_upload for file '{uploaded_file.name}': {e}",
                        exc_info=True
                    )
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
                logger.warning(
                    f"User '{user.username}': File '{uploaded_file.name}' failed validation. Errors: {error_string}"
                )
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


class DownloadFileView(LoginRequiredMixin, View):
    def get(self, request, file_id):
        user_file = get_object_or_404(UserFile, id=file_id, user=request.user)
        s3_client = get_s3_client()
        s3_key = user_file.file.name

        try:
            presigned_url = s3_client.generate_presigned_url(
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
        except ClientError as e:
            logger.error(f"Error generating presigned URL for s3_key: {s3_key}: {e}")
            raise Http404("Не удалось скачать файл")
        except ParamValidationError as e:
            logger.error(f"{e}")
            raise Http404("Не удалось скачать файл")

class DeleteView(LoginRequiredMixin, ListView):
    pass


class RenameView(LoginRequiredMixin, ListView):
    pass
