import logging
import urllib
from functools import wraps
from typing import Type, Any, Callable
from uuid import UUID

from botocore.exceptions import ClientError, ParamValidationError
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction, IntegrityError
from django.db.models import QuerySet
from django.http import JsonResponse, HttpResponseRedirect, StreamingHttpResponse, Http404, HttpRequest
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import ListView

from cloud_file_storage import settings
from file_storage.exceptions import (StorageError, NameConflictError, DatabaseError, InvalidPathError)
from file_storage.forms import FileUploadForm, DirectoryCreationForm, RenameItemForm
from file_storage.mixins import QueryParamMixin
from file_storage.models import UserFile, FileType
from file_storage.services import upload_service
from file_storage.services.archive_service import ZipStreamGenerator
from file_storage.services.directory_service import DirectoryService
from file_storage.services.upload_service import get_message_and_status
from file_storage.storages.minio import minio_client
from file_storage.utils import ui
from file_storage.utils.path_utils import encode_path_for_url

logger = logging.getLogger(__name__)

FILE_STORAGE_LIST_FILES_URL: str = 'file_storage:list_files'
FILE_LIST_TEMPLATE: str = 'file_storage/list_files.html'


def handle_service_exceptions(
        view_func: Callable[[HttpRequest, ...], Any]
) -> Callable[[HttpRequest, ...], Any]:
    """Декоратор для обработки общих исключений, возникающих в view-функциях.

    Ловит ``UserFile.DoesNotExist``, ``ValueError``, ``TypeError`` и любые другие ``Exception``,
    возвращая стандартизированный JSON-ответ об ошибке.

    :param view_func: Оборачиваемая view-функция или метод.
    :return: Обёрнутая функция/метод с обработкой исключений.
    """

    @wraps(view_func)
    def _wrapped_view_func(request: HttpRequest, *args, **kwargs):
        try:
            return view_func(request, *args, **kwargs)
        except UserFile.DoesNotExist:
            return JsonResponse(
                {'message': 'Родительская папка не найдена'},
                status=404,
            )
        except (ValueError, TypeError):
            return JsonResponse(
                {'message': 'Передан некорректный идентификатор или тип данных.'},
                status=400
            )
        except Exception as e:
            logger.critical(f"Unexpected error: {e}", exc_info=True)
            return JsonResponse(
                {'message': 'Неизвестная ошибка на сервере, попробуйте позже'},
                status=500
            )

    return _wrapped_view_func


class FileListView(QueryParamMixin, LoginRequiredMixin, ListView):
    """
    Отображает список файлов и папок для аутентифицированного пользователя.

    Метод post создает новую папку.
    Позволяет навигацию по директориям. Поддерживает пагинацию.
    """
    model: Type[UserFile] = UserFile
    template_name: str = FILE_LIST_TEMPLATE
    context_object_name = 'items'
    paginate_by = 20

    def setup(self, request: HttpRequest, *args, **kwargs) -> None:
        """
        Инициализирует атрибуты представления перед вызовом dispatch.

        Устанавливает текущего пользователя, необработанный путь из GET-параметра 'path'
        и объект текущей директории.

        :param request: Объект HTTP-запроса.
        :param args: Позиционные аргументы.
        :param kwargs: Именованные аргументы.
        """
        super().setup(request, *args, **kwargs)
        self.user: User = request.user
        self.current_path_unencoded: str = request.GET.get('path', '')
        self.current_directory: UserFile | None = DirectoryService.get_current_directory_from_path(
            self.user, self.current_path_unencoded
        )

    def get_queryset(self) -> QuerySet[UserFile]:
        """
        Формирует и возвращает queryset файлов и папок для текущей директории.

        Фильтрует объекты `UserFile` по текущему пользователю и
        родительской директории (:attr:`current_directory`).
        Если `current_directory` равен ``None``, это означает корневую
        директорию пользователя (объекты, у которых `parent` равен ``None``).
        Результаты упорядочиваются по типу объекта (сначала папки), затем по имени.

        :return: QuerySet отфильтрованных и упорядоченных объектов.
        """
        queryset: QuerySet[UserFile] = UserFile.objects.filter(
            user=self.user, parent=self.current_directory
        )

        if not self.current_directory:
            self.current_directory = None

        logger.info(
            f"User: '{self.user}' has successfully moved to the '{self.current_directory}' directory.")

        return queryset.order_by('object_type', 'name')

    def get_context_data(self, **kwargs) -> dict[str, Any]:
        """
        Формирует и возвращает контекст данных для шаблона.

        Добавляет в контекст информацию о текущей директории, пути,
        "хлебные крошки", URL для кнопки "Назад", ID текущей папки
        и форму для создания новой директории.

        :param kwargs: Дополнительные аргументы контекста.
        :return: Словарь данных контекста.
        """
        context: dict = super().get_context_data(**kwargs)

        context['current_directory'] = self.current_directory
        context['current_path_unencoded'] = self.current_path_unencoded
        context['breadcrumbs'] = ui.generate_breadcrumbs(self.current_path_unencoded)
        context['DATA_UPLOAD_MAX_NUMBER_FILES'] = settings.DATA_UPLOAD_MAX_NUMBER_FILES
        context['DATA_UPLOAD_MAX_MEMORY_SIZE'] = settings.DATA_UPLOAD_MAX_MEMORY_SIZE

        # Формирование URL для кнопки "Назад"
        context['parent_level_url'] = ui.get_parent_url(
            self.current_path_unencoded, FILE_STORAGE_LIST_FILES_URL
        )

        current_directory_id = self.current_directory.id if self.current_directory else None

        context['current_folder_id'] = current_directory_id
        context['form_create_folder'] = DirectoryCreationForm(user=self.user)

        return context

    @handle_service_exceptions
    def post(self, request: HttpRequest, *args, **kwargs) -> JsonResponse:
        """Обрабатывает POST-запрос для создания новой папки.

        Валидирует данные формы и, в случае успеха, вызывает сервис для создания папки.

        :param request: HTTP-запрос.
        :param args: Дополнительные позиционные аргументы.
        :param kwargs: Дополнительные именованные аргументы.
        :return: JSON-ответ со статусом операции.
        """
        form = DirectoryCreationForm(request.user, request.POST)

        if not form.is_valid():
            logger.warning(
                f"User '{self.user.username}': Form validation failed. "
                f"errors: {form.errors['name'].data}"
            )
            return JsonResponse(
                {'status': 'error',
                 'message': f'{form.errors["name"][0]}',
                 'errors': form.errors.as_json()},
                status=400
            )

        parent_pk: str = request.POST.get('parent', '')
        directory_name: str = form.cleaned_data['name']

        try:
            DirectoryService.create(self.user, directory_name, parent_pk)
            return JsonResponse({
                'status': 'success',
                'message': 'Папка успешно создана!',
            }, status=201)

        except NameConflictError as e:
            return JsonResponse({
                'status': 'error',
                'message': f'{e}'
            }, status=400)

        except DatabaseError:
            return JsonResponse({
                'status': 'error',
                'message': 'Ошибка базы данных: Не удалось создать папку из-за конфликта данных.',
            }, status=409)

        except StorageError:
            return JsonResponse({
                'status': 'error',
                'message': 'Ошибка хранилища. Не удалось создать папку.'
            }, status=500)


class FileUploadAjaxView(LoginRequiredMixin, View):
    """View для обработки AJAX-запросов на загрузку файлов и папок."""

    @staticmethod
    def _handle_form_validation_error(form: FileUploadForm) -> str:
        """
        Формирует строку ошибок из невалидной формы.

        :param form: Экземпляр невалидной формы ``FileUploadForm``.
        :return: Строка, содержащая все сообщения об ошибках.
        """
        error_messages: list[str] = []
        for field, errors in form.errors.items():
            error_messages.append(f"{field}: {'; '.join(errors)}")
        error_string: str = "; ".join(error_messages)
        return error_string

    @handle_service_exceptions
    def post(self, request: HttpRequest, *args, **kwargs) -> JsonResponse:
        """
        Обрабатывает POST-запрос на загрузку файлов.

        Принимает список файлов и опционально относительные пути для каждого файла
        для создания вложенных директорий.

        :param request: Объект HttpRequest.
        :return: JsonResponse с результатами загрузки.
        """
        relative_paths = request.POST.getlist('relative_paths')
        parent_id: str = request.POST.get('parent_id', '')
        files = request.FILES.getlist('files')
        user: User = request.user

        if not files:
            logger.warning(f"User: '{user.username}': File upload request received without files.")
            return JsonResponse({'error': 'Файл отсутствует'}, status=400)

        parent_object: UserFile | None = DirectoryService.get_parent_directory(user, parent_id)

        num_files = len(files)

        if not relative_paths:
            relative_paths = [None for i in range(num_files)]

        logger.info(
            f"User: '{user.username}' ID: {user.id} initiated {num_files} files upload. "
            f"Target parent_id: '{parent_id}'."
        )

        results: list[dict[str, str]] = []
        cache: dict[str, UserFile] = {}
        for uploaded_file, rel_path in zip(files, relative_paths):
            form_data: dict[str, Any] = {'parent': parent_object.pk if parent_object else None}
            form_files: dict[str, UploadedFile] = {'file': uploaded_file}
            form = FileUploadForm(form_data, form_files, user=user)

            if form.is_valid():
                try:
                    with transaction.atomic():
                        dir_path_cache, parent_object_cache = upload_service.handle_file_upload(
                            uploaded_file, user, parent_object, rel_path, cache
                        )
                        result: dict[str, str] = {'name': uploaded_file.name, 'status': 'success'}
                        results.append(result)

                        if dir_path_cache and dir_path_cache not in cache:
                            cache[dir_path_cache] = parent_object_cache

                except InvalidPathError as e:
                    logger.error(
                        f"User: '{user.username}'. Invalid relative path: {rel_path}. {e}",
                        exc_info=True
                    )
                    results.append({
                        'name': uploaded_file.name,
                        'status': 'error',
                        'error': f'Некорректный относительный путь {rel_path}'
                    })

                except StorageError:
                    results.append({
                        'name': uploaded_file.name,
                        'status': 'error',
                        'error': 'Ошибка Хранилища',
                    })

                except NameConflictError:
                    results.append({
                        'name': uploaded_file.name,
                        'status': 'error',
                        'error': 'Такой файл уже существует'
                    })

            else:
                error_string: str = FileUploadAjaxView._handle_form_validation_error(form)
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
    """
    Отображает результаты поиска файлов и папок пользователя.

    Поиск выполняется по имени файла/папки (без учета регистра).
    Используется Пагинация.
    """

    template_name: str = 'file_storage/search_results.html'
    paginate_by: int = 25
    context_object_name: str = 'search_results'

    query: str | None = None

    def setup(self, request: HttpRequest, *args, **kwargs) -> None:
        """Инициализирует атрибут `query` из GET-параметра 'query'."""
        super().setup(request, *args, **kwargs)
        self.query = self.request.GET.get('query', None)

    def get_queryset(self) -> QuerySet[UserFile]:
        """
        Формирует queryset для поиска файлов и папок.

        Если поисковый запрос `self.query` не задан, возвращает пустой queryset.
        В противном случае, фильтрует объекты :model:`UserFile`
        по текущему пользователю и совпадению имени с `self.query` (без учета регистра).
        Результаты упорядочиваются по типу объекта (папки сначала), затем по имени.

        :return: Queryset с результатами поиска.
        """
        if not self.query:
            return UserFile.objects.none()

        return UserFile.objects.filter(
            user=self.request.user, name__icontains=self.query
        ).order_by('object_type', 'name')

    def get_context_data(self, **kwargs) -> dict[str, Any]:
        """
        Добавляет поисковый запрос и закодированный текущий путь в контекст.

        `unencoded_path` берется из GET-параметра 'current_path_unencoded'
        и используется для формирования URL для возможного возврата в предыдущую директорию.

        :return: Словарь с данными контекста.
        :context query: Текущий поисковый запрос.
        :context encoded_path: URL-закодированный путь, полученный из `current_path_unencoded`.
        """
        context: dict[str, Any] = super().get_context_data(**kwargs)

        unencoded_path: str = self.request.GET.get('current_path_unencoded', '')
        encoded_path: str = encode_path_for_url(unencoded_path, FILE_STORAGE_LIST_FILES_URL)

        context['query'] = self.query
        context['encoded_path'] = encoded_path

        return context


class DownloadFileView(LoginRequiredMixin, View):
    """
    Обрабатывает запросы на скачивание одного файла.

    При GET-запросе проверяет права пользователя на файл, его наличие в S3,
    генерирует presigned URL для скачивания и перенаправляет пользователя по этому URL.
    В случае ошибки или если файл не найден, показывает сообщение и перенаправляет
    пользователя обратно на страницу, с которой был сделан запрос (или на страницу списка файлов).
    """

    def get(self, request: HttpRequest, file_id: int) -> HttpResponseRedirect:
        """
        Обрабатывает GET-запрос на скачивание файла.

        :param request: Объект HttpRequest.
        :param file_id: ID файла (UserFile) для скачивания.
        :return: HttpResponseRedirect на presigned URL для скачивания файла
                 или на предыдущую страницу/список файлов в случае ошибки.
        """
        unencoded_path: str = request.GET.get("path_param", "")
        encoded_path = encode_path_for_url(unencoded_path, FILE_STORAGE_LIST_FILES_URL)

        try:
            user_file = get_object_or_404(
                UserFile, id=file_id, user=request.user, object_type=FileType.FILE
            )
        except Http404:
            logger.warning(
                f"Попытка доступа к несуществующему или чужому файлу: id={file_id}, "
                f"user={request.user.id}"
            )
            messages.warning(request, "Запрошенный файл не найден или "
                                      "у вас нет прав на его скачивание.")
            return redirect(encoded_path)

        s3_key: str = user_file.file.name

        try:
            if minio_client.check_files_exist((user_file,)):
                presigned_url: str = minio_client.s3_client.generate_presigned_url(
                    'get_object',
                    Params={
                        'Bucket': settings.AWS_STORAGE_BUCKET_NAME,
                        'Key': s3_key,
                        'ResponseContentDisposition': f'attachment; filename="{user_file.name}"'
                    },
                    ExpiresIn=1700
                )
                logger.info(
                    f"File downloaded successfully. s3_key: {s3_key}, presigned_url: {presigned_url}")
                return HttpResponseRedirect(presigned_url)

            else:
                logger.warning(
                    f"User: '{user_file.user}. File does not found in s3/minio storage'",
                    exc_info=True
                )
                messages.warning(request, f"Такого файла: '{user_file}' не существует")

        except ClientError as e:
            logger.error(f"Error generating presigned URL for s3_key: {s3_key}: {e}")
            messages.error(
                request, "Произошла ошибка при обращении к хранилищу, попробуйте позже"
            )
        except ParamValidationError as e:
            logger.error(f"{e}")
            messages.error(request, "Произошла ошибка при запросе к хранилищу")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            messages.error(request, "Произошла ошибка при скачивании файла, попробуйте позже")

        return redirect(encoded_path)


class DownloadDirectoryView(LoginRequiredMixin, View):
    """Обрабатывает запросы на скачивание директории пользователя в виде ZIP-архива."""

    def get(self, request: HttpRequest, directory_id: int) -> StreamingHttpResponse | Any:
        """
        Обрабатывает GET-запрос для скачивания директории.

        При успешном выполнении инициирует потоковую передачу ZIP-архива,
        содержащего все файлы и подпапки указанной директории.
        В случае ошибок (например, папка не найдена, нет прав доступа,
        проблемы с чтением файлов из хранилища) перенаправляет пользователя
        на предыдущую страницу с соответствующим сообщением.

        :param request: HTTP-запрос.
        :param directory_id: Идентификатор директории (объекта UserFile) для скачивания.
        :returns: StreamingHttpResponse с ZIP-архивом или HttpResponseRedirect в случае ошибки.
        """
        unencoded_path: str = request.GET.get("path_param", "")
        encoded_path = encode_path_for_url(unencoded_path, FILE_STORAGE_LIST_FILES_URL)

        user: User = request.user

        try:
            directory: UserFile = get_object_or_404(
                UserFile, id=directory_id, user=user, object_type=FileType.DIRECTORY
            )
        except Http404:
            logger.warning(
                f"Попытка доступа к несуществующей или чужой папке: id={directory_id}, "
                f"user={request.user}"
            )
            messages.warning(request, "Запрошенная папка не найдена или "
                                      "у вас нет прав на её скачивание.")
            return redirect(encoded_path)

        all_files = UserFile.objects.get_all_children_files(directory)

        if not minio_client.check_files_exist(all_files):
            messages.error(request, "Не удалось прочитать некоторые файлы из хранилища")
            return redirect(encoded_path)

        zip_generator = ZipStreamGenerator(directory, all_files)

        zip_filename = f"{directory.name}.zip"
        encoded_zip_filename: str = urllib.parse.quote(zip_filename)

        try:
            response = StreamingHttpResponse(
                zip_generator.generate(), content_type='application/zip'
            )
        except StorageError:
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
    """Обрабатывает удаление файлов и папок пользователя."""

    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponseRedirect:
        """
        Обрабатывает POST-запрос на удаление объекта.

        Получает ID объекта и путь для редиректа из тела запроса.
        Проверяет, что объект принадлежит текущему пользователю,
        прежде чем инициировать удаление через DirectoryService.

        :param request: Объект HTTP-запроса.
        :param args: Дополнительные позиционные аргументы.
        :param kwargs: Дополнительные именованные аргументы.
        :return: Редирект на страницу, с которой был сделан запрос.
        """
        user: User = request.user

        unencoded_path: str = request.POST.get("unencoded_path", "")
        encoded_path: str = encode_path_for_url(unencoded_path, FILE_STORAGE_LIST_FILES_URL)

        item_id: str | None = request.POST.get('item_id')

        try:
            storage_object: UserFile = get_object_or_404(UserFile, user=user, id=item_id)
        except Http404:
            logger.warning(
                f"Попытка доступа к несуществующей или чужой папке при удалении: id={item_id}, "
                f"user={request.user}"
            )
            messages.warning(request, "Запрошенный файл не найден.")
            return redirect(encoded_path)

        try:
            DirectoryService.delete_obj(storage_object)
            messages.success(
                request, f"{storage_object.get_object_type_display()} успешно удален(а)!"
            )

        except StorageError as e:
            logger.error(f"User '{user}'. Error while deleting '{storage_object}' from s3. {e}",
                         exc_info=True)
            messages.error(request, "Удалить объект не получилось.")

        return redirect(encoded_path)


class RenameView(LoginRequiredMixin, View):
    """Обрабатывает POST-запрос для переименования файла или папки пользователя."""

    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponseRedirect:
        """
        Обрабатывает переименование объекта.

        Получает из POST-запроса ID объекта, новое имя и текущий путь для редиректа.
        Валидирует данные, выполняет операцию переименования через слой сервисов
        и обрабатывает возможные ошибки, информируя пользователя через `django.contrib.messages`.

        :param request: Объект HttpRequest.
        :param args: Позиционные аргументы.
        :param kwargs: Именованные аргументы.
        :return: Объект HttpResponseRedirect (редирект).
        """
        unencoded_path: str = request.POST.get("unencoded_path", "")
        item_id: str = request.POST.get('id', '')
        user: User = request.user
        new_name: str = request.POST.get('name', '')

        encoded_path: str = encode_path_for_url(unencoded_path, FILE_STORAGE_LIST_FILES_URL)

        if not item_id:
            logger.warning(f"User '{user}'. Object ID was not transmitted")
            messages.error(
                request, "Не удалось определить объект для переименования (ID отсутствует)."
            )
            return redirect(encoded_path)

        try:
            object_instance = get_object_or_404(UserFile, user=user, id=item_id)
        except (ValidationError, Http404) as e:
            logger.warning(
                f"User '{user}'. Invalid type received. UUID required. {type(item_id)} received. {e}",
                exc_info=True
            )
            messages.warning(
                request, "Переименовать объект не удалось. "
                         "Неправильный ID объекта или объект не найден."
            )
            return redirect(encoded_path)

        if UserFile.objects.object_with_name_exists(user, new_name, object_instance.parent):
            logger.warning(f"User '{user}' tried to save an object with an existing one.")
            messages.warning(request, "Файл или папка с таким именем уже существует.")
            return redirect(encoded_path)

        form = RenameItemForm(request.POST, instance=object_instance)
        if form.is_valid():
            try:
                DirectoryService.rename(object_instance, form)

                logger.info(f"User '{user}' renamed {object_instance.object_type} "
                            f"to '{form.cleaned_data['name']}'")
                messages.success(
                    request,
                    f"{object_instance.get_object_type_display()} успешно переименован(а)"
                )

            except IntegrityError as e:
                logger.warning(
                    f"User: '{user}'. Error while renaming object. '{object_instance.object_type}' "
                    f"with that name already exists with ID {object_instance.id}.\n{e}. ",
                    exc_info=True
                )
                messages.warning(
                    request,
                    f"{object_instance.get_object_type_display()} с таким именем уже существует"
                )
            except StorageError as e:
                logger.error(f"User '{user}'. Error getting s3/minio keys. {e}", exc_info=True)
                messages.error(request, "Переименовать объект не получилось. "
                                        "Не удалось получить ключи для удаления из хранилища")
            except Exception as e:
                logger.warning(f"User: '{user}'. Error while renaming '{object_instance.object_type}'"
                               f"with ID {object_instance.id}.\n{e}", exc_info=True)
                messages.error(request, "Произошла ошибка при переименовании")

        else:
            messages.warning(
                request, form.errors.get('name', ["Неизвестная ошибка валидации имени."])[0]
            )

        return redirect(encoded_path)


class MoveStorageItemView(LoginRequiredMixin, View):
    """Обрабатывает POST-запрос для перемещения файла или папки пользователя."""

    def post(self, request: HttpRequest) -> HttpResponseRedirect:
        """
        Обрабатывает POST-запрос на перемещение файла или папки.

        Получает из запроса ID перемещаемого объекта, путь для редиректа
        и ID папки назначения. Вызывает сервис для выполнения логики
        перемещения и обрабатывает возможные исключения.

        :param request: Объект HTTP-запроса.
        :return: Перенаправление на исходный URL.
        :raises: Неявно обрабатывает и логирует исключения,
                 возвращая пользователю сообщение об ошибке.
        """
        item_id: str = request.POST.get('item_id_to_move')
        unencoded_path: str = request.POST.get('unencoded_path')
        destination_folder_id: str = request.POST.get('destination_folder_id', '')

        encoded_path = encode_path_for_url(unencoded_path, FILE_STORAGE_LIST_FILES_URL)
        try:
            DirectoryService.move(request.user, item_id, destination_folder_id)
        except ValidationError as e:
            logger.warning(
                f"User: '{request.user}'. "
                f"Invalid type received. UUID required. {type(item_id)} received. {e}",
                exc_info=True
            )
            messages.warning(request, "Неправильный ID объекта")
        except UserFile.DoesNotExist as e:
            logger.warning(
                f"User: '{request.user}'. "
                f"Storage_object with ID: {destination_folder_id} does not exists. {e}",
                exc_info=True,
            )
            messages.warning(request, "Такого объекта не существует")
        except StorageError as e:
            logger.error(f"User '{request.user}'. Error getting s3/minio keys. {e}", exc_info=True)
            messages.error(request, "Переместить объект не получилось. "
                                    "Не удалось получить ключи для удаления из хранилища")
        except NameConflictError as e:
            logger.warning(e, exc_info=True)
            messages.warning(request, e)
        except Exception as e:
            logger.error(
                f"User: '{request.user}'. "
                f"Unknown error. Storage_object with ID: {destination_folder_id}. {e}",
                exc_info=True,
            )
            messages.error(request, "Неизвестная ошибка")

        return redirect(encoded_path)


class DestinationFolderAjaxView(LoginRequiredMixin, View):
    """Обрабатывает AJAX-запрос для получения списка доступных директорий для перемещения."""

    def get(self, request: HttpRequest) -> JsonResponse:
        """
        Возвращает JSON-список директорий, в которые можно переместить объект.

        Принимает GET-параметр 'item_id' для идентификации перемещаемого объекта.

        :param request: Объект запроса Django.
        :return: JsonResponse со списком директорий или с ошибкой.
                 Успешный ответ: [{"id": 1, "display_name": "path/to/folder"}, ...]
                 Ответ с ошибкой: {"error": "сообщение"}
        """
        item_id: str = request.GET.get('item_id', '')
        if not item_id:
            return JsonResponse(
                {'error': 'Объект для перемещения не передан'},
                status=400,
            )
        available_directories = UserFile.objects.available_directories_to_move(request.user, item_id)
        data: list[dict[str, str | UUID]] = []
        for directory in available_directories:
            data.append({"id": directory.id, "display_name": directory.get_display_path})

        return JsonResponse(data, safe=False, status=200)
