import logging

from django.contrib.auth.models import User
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction

from file_storage.exceptions import InvalidPathError, StorageError
from file_storage.models import UserFile
from file_storage.services.directory_service import DirectoryService
from file_storage.services.file_service import FileService

logger = logging.getLogger(__name__)


class UploadService:
    """
    Предоставляет бизнес-логику для операций, связанных с загрузкой файлов.

    Этот сервис инкапсулирует логику по созданию необходимых директорий
    и непосредственному сохранению файла, координируя работу
    DirectoryService и FileService. Является частью слоя сервисов (Service Layer).
    """

    def __init__(self, user: User, directory_service: DirectoryService, file_service: FileService):
        """
        Инициализирует сервис.

        Принимает пользователя, для которого выполняется операция.
        Принимает другие сервисы, от которых зависит его работа (инъекция зависимостей).

        :param user: Экземпляр пользователя Django, инициировавший загрузку.
        :param directory_service: Сервис для работы с директориями.
        :param file_service: Сервис для работы с файлами.
        """
        self.user = user
        self.directory_service = directory_service
        self.file_service = file_service
        self._directory_cache: dict[str, UserFile] = {}

    def upload_file(
            self, uploaded_file: UploadedFile, rel_path: str | None, parent_object: UserFile | None
    ) -> None:
        """Атомарно обрабатывает загрузку одного файла.

        Функция использует внешний кэш для отслеживания уже
        созданных директорий в рамках одной транзакции,
        чтобы избежать повторных обращений к базе данных.

        :param parent_object: Изначальная родительская директория (UserFile) или None.
        :param uploaded_file: Объект загруженного файла.
        :param rel_path: Относительный путь, по которому нужно создать вложенные папки.

        :raises: Может пробрасывать исключения из `handle_file_upload` (например,
                 `NameConflictError`, `StorageError`), что приведет к откату транзакции.
        """
        with transaction.atomic():
            dir_path_cache, parent_object_cache = self._handle_file_upload(
                uploaded_file, rel_path, self._directory_cache, parent_object
            )

            if dir_path_cache and dir_path_cache not in self._directory_cache:
                self._directory_cache[dir_path_cache] = parent_object_cache

    def _handle_file_upload(
            self,
            uploaded_file: UploadedFile,
            relative_path: str | None,
            cache: dict[str, UserFile],
            parent_object
    ) -> tuple[str | None, UserFile]:
        """
        Обрабатывает загрузку одного файла.

        Создает необходимые директории на основе ``relative_path`` (если указан),
        создает запись ``UserFile`` в базе данных и загружает файл в S3/Minio.
        Использует кэш ``cache`` для оптимизации создания директорий.

        :param uploaded_file: Загружаемый файл.
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
        uploaded_file_name = uploaded_file.name
        dir_path: str | None = None
        log_prefix: str = (f"User '{self.user}' (ID: {self.user.id}), File '{uploaded_file_name}', "
                           f"Parent ID: {parent_object.id if parent_object else 'None'}, "
                           f"relative_path: {relative_path}")

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
                    parent_object = self.directory_service.get_parent_or_create_directories_from_path(
                        parent_object, directory_path_parts
                    )

                except StorageError:
                    # Логирвание ниже в get_parent_or_create_directories_from_path
                    raise

            else:
                parent_object = cache[dir_path]

        self.file_service.create_file(uploaded_file, parent_object, log_prefix)
        return dir_path, parent_object
