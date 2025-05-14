import logging
import urllib

from botocore.exceptions import NoCredentialsError, BotoCoreError, ClientError
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction, IntegrityError
from django.http import Http404, JsonResponse
from django.urls import reverse
from django.views import View
from django.views.generic import CreateView, ListView

from cloud_file_storage import settings
from file_storage.forms import FileUploadForm, DirectoryCreationForm
from file_storage.mixins import StorageSuccessUrlMixin, UserFormKwargsMixin, ParentInitialMixin
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

        return context


class FileUploadAjaxView(LoginRequiredMixin, View):
    def _handle_file_upload(self, uploaded_file, user, parent_object):
        """
        Обрабатывает один загруженный файл: проверяет, создает UserFile, загружает файл в Minio через FileField.
        Возвращает словарь с результатом.
        """

        uploaded_file_name = uploaded_file.name

        log_prefix = (f"User '{user.username}' (ID: {user.id}), File '{uploaded_file_name}', "
                      f"Parent ID: {parent_object.id if parent_object else 'None'}:")

        if UserFile.objects.filter(
                user=user,
                parent=parent_object,
                name=uploaded_file_name
        ).exists():
            logger.warning(f"{log_prefix} Upload failed. File with this name already exists.")
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

                logger.info(
                    f"{log_prefix} Successfully uploaded and saved. "
                    f"UserFile ID: {user_file_instance.id}, Minio Path: {user_file_instance.file.name}"
                )

                return {
                    'name': user_file_instance.name,
                    'status': 'success',
                    'id': str(user_file_instance.id)
                }

        except Exception as e:
            logger.error(
                f"{log_prefix} Error during file save or Minio upload: {e}",
                exc_info=True  # Добавляет traceback в лог
            )
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

        logger.info(
            f"{self.__class__.__name__}: User '{user.username}' ID: {user.id} initiated file upload. "
            f"Number of files: {len(files)}. Target parent_id: '{parent_id}'."
        )

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
            except Exception as e:
                logger.error(
                    f"User '{user.username}': Unexpected error finding parent directory ID '{parent_id}': {e}.",
                    exc_info=True
                )
                return JsonResponse(
                    data={'error': 'Ошибка на стороне сервера'},
                    status=500,
                )

        if not files:
            logger.warning(f"User '{user.username}': File upload request received without files.")
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

        raw_parent_pk = self.request.POST.get('parent')
        parent_object = None

        logger.info(
            f"{self.__class__.__name__}: User: '{form.instance.user.username}' ID: {self.request.user.id} "
            f"initiates creation of {form.instance.object_type}. "
            f"raw_parent_pk: {raw_parent_pk}"
        )

        if raw_parent_pk:
            try:
                parent_object = UserFile.objects.get(
                    pk=raw_parent_pk,
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
                    f"Parent directory not found. pk={raw_parent_pk} user={self.request.user.username} ID: {self.request.user.id} "
                    f"Requested parent_pk: '{raw_parent_pk}'. Query was for object_type: {FileType.DIRECTORY}"
                )
                form.add_error(None, "Родительская папка не найдена или не является директорией.")
                return self.form_invalid(form)
            except (ValueError, TypeError):
                logger.error(
                    f"User={self.request.user.username} ID: {self.request.user.id} "
                    f"object_type={FileType.DIRECTORY} Invalid parent folder identifier. pk={raw_parent_pk}",
                    exc_info=True
                )
                form.add_error(None, "Некорректный идентификатор родительской папки.")
                return self.form_invalid(form)

        form.instance.parent = parent_object

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
                logger.info(f"Directory successfully created in DB and S3. Path={key}, DB ID={form.instance.pk}")
                messages.success(self.request, "Папка успешно создана")
                return response

        except IntegrityError as e:
            logger.error(f"Database integrity error during folder creation: {e}", exc_info=True)
            form.add_error(None,
                           "Ошибка базы данных: Не удалось создать папку из-за конфликта данных.")
            return self.form_invalid(form)

        except NoCredentialsError:
            logger.critical("S3/Minio credentials not found. Cannot create directory marker.", exc_info=True)
            messages.error(
                self.request,
                "Ошибка конфигурации сервера: Не удалось подключиться к хранилищу файлов."
            )
            return self.form_invalid(form)

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")
            logger.error(f"S3 ClientError while creating directory marker '{key}': {e} (Code: {error_code})",
                         exc_info=True)
            messages.error(self.request,
                           f"Ошибка хранилища. Не удалось создать папку в облаке.")
            return self.form_invalid(form)

        except BotoCoreError as e:
            logger.error(f"BotoCoreError while creating directory marker '{key}': {e}", exc_info=True)
            messages.error(
                self.request, "Произошла ошибка при взаимодействии с файловым хранилищем. Попробуйте позже."
            )
            return self.form_invalid(form)

        except AttributeError as e:
            logger.error(
                f"AttributeError, possibly related to form.instance or S3 key generation: {e}", exc_info=True
            )
            messages.error(self.request, "Внутренняя ошибка сервера при подготовке данных для хранилища.")
            return self.form_invalid(form)

        except Exception as e:
            logger.critical(f"Unexpected error during folder creation (S3 part): {e}", exc_info=True)
            messages.error(self.request, "Произошла непредвиденная ошибка при создании папки.")
            return self.form_invalid(form)


class DeleteView(LoginRequiredMixin, ListView):
    pass


class RenameView(LoginRequiredMixin, ListView):
    pass
