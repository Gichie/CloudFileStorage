import logging

from django.contrib.auth.models import User
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction

from file_storage.exceptions import StorageError, InvalidPathError
from file_storage.models import UserFile
from file_storage.services.directory_service import DirectoryService
from file_storage.services.file_service import FileService

logger = logging.getLogger(__name__)


def upload_file(
        user: User,
        uploaded_file: UploadedFile,
        parent_object: UserFile | None,
        rel_path: str | None,
        cache: dict[str, UserFile]
) -> None:
    """Атомарно обрабатывает загрузку одного файла.

    Функция использует внешний кэш для отслеживания уже
    созданных директорий в рамках одной транзакции,
    чтобы избежать повторных обращений к базе данных.

    :param user: Пользователь, который загружает файл.
    :param uploaded_file: Объект загруженного файла.
    :param parent_object: Родительский объект для загрузки.
    :param rel_path: Относительный путь, по которому нужно создать вложенные папки.
    :param cache: Кэш уже созданных директорий для текущей сессии загрузки.
                  Функция модифицирует этот объект.

    :raises: Может пробрасывать исключения из `handle_file_upload` (например,
             `NameConflictError`, `StorageError`), что приведет к откату транзакции.
    """
    with transaction.atomic():
        dir_path_cache, parent_object_cache = handle_file_upload(
            uploaded_file, user, parent_object, rel_path, cache
        )

        if dir_path_cache and dir_path_cache not in cache:
            cache[dir_path_cache] = parent_object_cache


def handle_file_upload(
        uploaded_file: UploadedFile,
        user: User,
        parent_object: UserFile | None,
        relative_path: str | None,
        cache: dict[str, UserFile]
) -> tuple[str | None, UserFile | None]:
    """
    Обрабатывает загрузку одного файла.

    Создает необходимые директории на основе ``relative_path`` (если указан),
    создает запись ``UserFile`` в базе данных и загружает файл в S3/Minio.
    Использует кэш ``cache`` для оптимизации создания директорий.

    :param uploaded_file: Загружаемый файл.
    :param user: Пользователь, загружающий файл.
    :param parent_object: Изначальная родительская директория (UserFile) или None.
    :param relative_path: Относительный путь для файла (например, "subfolder/file.txt").
                          Если None, файл загружается в ``parent_object``.
    :param cache: Кэш для уже обработанных путей директорий.
    :raises InvalidPathError: Если ``relative_path`` некорректен.
    :raises StorageError: Если произошла ошибка при взаимодействии с S3/Minio.
    :return: Кортеж (dir_path, parent_object).
             ``dir_path``: Относительный путь к созданной/найденной директории (ключ для кэша),
                           или None, если файл загружается напрямую в ``parent_object``.
             ``parent_object``: Родительский объект UserFile для создаваемого файла,
                                   может быть None, если это корень.
    """
    uploaded_file_name: str = uploaded_file.name
    dir_path: str | None = None
    log_prefix: str = (f"User '{user.username}' (ID: {user.id}), File '{uploaded_file_name}', "
                       f"Parent ID: {parent_object.id if parent_object else 'None'}, relative_path: {relative_path}")

    with transaction.atomic():
        if relative_path:
            path_components: list[str] = [component for component in relative_path.split('/') if
                                          component]
            dir_path = '/'.join(path_components[:-1])

            if not path_components:
                logger.error(f"Invalid relative path {log_prefix}")
                raise InvalidPathError()

            directory_path_parts: list[str] = path_components[:-1]

            if dir_path not in cache:
                try:
                    parent_object = DirectoryService.get_parent_or_create_directories_from_path(
                        user, parent_object, directory_path_parts
                    )

                except StorageError:
                    # Логирвание ниже в get_parent_or_create_directories_from_path
                    raise

            else:
                parent_object = cache[dir_path]

        FileService.create_file(user, uploaded_file, parent_object, log_prefix)
        return dir_path, parent_object


def get_message_and_status(results: list[dict[str, str]]) -> tuple[dict[str, str], int]:
    """
    Формирует общее сообщение и HTTP-статус на основе результатов обработки файлов.

    :param results: Список словарей, где каждый словарь представляет результат
                    обработки одного файла и содержит ключи 'status' и 'name'.
    :return: Кортеж из словаря с сообщением и списком результатов, и HTTP-статуса.
             HTTP-статус 200 если все успешно, 207 (Multi-Status) если были ошибки.
    """
    any_errors: bool = any(res['status'] == 'error' for res in results)

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

    return {'message': message, 'results': results}, http_status
