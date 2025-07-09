import logging
from uuid import UUID

import boto3
from botocore.config import Config
from botocore.exceptions import ParamValidationError
from django.contrib.auth.models import User
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction

from cloud_file_storage import settings
from cloud_file_storage.settings import PRESIGNED_URL_LIFETIME_SECONDS
from file_storage.exceptions import DatabaseError, InvalidPathError, NameConflictError, StorageError
from file_storage.models import FileType, UserFile
from file_storage.storages.minio import MinioClient, minio_client

logger = logging.getLogger(__name__)


class FileService:
    """
    Сервис для управления файлами пользователя в S3-совместимом хранилище.

    Предоставляет бизнес-логику для операций с файлами, инкапсулируя
    взаимодействие с моделью UserFile и S3-клиентом.
    """

    def __init__(self, user: User, s3_client: MinioClient = minio_client):
        """
        Инициализирует сервис для конкретного пользователя.

        :param user: Экземпляр пользователя Django, от имени которого выполняются операции.
        :param s3_client: Клиент для работы с S3/Minio. Если не передан,
                          будет использован клиент по умолчанию.
        """
        self.user = user
        self.s3_client = s3_client

    def create_file(
            self, uploaded_file: UploadedFile, parent_object: UserFile | None, log_prefix: str
    ) -> None:
        """
        Создает запись о файле в БД и загружает его в хранилище.

        Проверяет, существует ли уже файл или папка с таким именем в данной
        директории. Если нет, создает экземпляр модели UserFile, что инициирует
        загрузку файла в Minio через настроенный storage backend Django.

        :param uploaded_file: Загружаемый файл (экземпляр UploadedFile из Django).
        :param parent_object: Родительский объект (директория), в который загружается файл.
        :param log_prefix: Префикс для логов.
        :raises NameConflictError: Если файл или папка с таким именем уже существует
                                   в родительской директории.
        :raises InvalidPathError: Если путь к файлу является некорректным
                                  (например, слишком длинный), что вызывает SuspiciousFileOperation.
        :return: None.
        """
        assert uploaded_file.name is not None, "Загружаемый файл должен иметь имя"

        if UserFile.objects.file_exists(self.user, parent_object, uploaded_file.name):
            message = f"Upload failed. File or directory with this name already exists. {log_prefix}"
            logger.error(message, exc_info=True)
            parent_name = parent_object.name if parent_object else None
            raise NameConflictError('Такой файл уже существует', uploaded_file.name, parent_name)

        try:
            with transaction.atomic():
                user_file_instance = UserFile(
                    user=self.user,
                    file=uploaded_file,
                    name=uploaded_file.name,
                    parent=parent_object,
                    object_type=FileType.FILE,
                )
                user_file_instance.save()

                logger.debug(
                    f"{user_file_instance.object_type} successfully uploaded and saved. {log_prefix}. "
                    f"UserFile ID: {user_file_instance.id}, Minio Path: {user_file_instance.file.name}"
                )

        except SuspiciousFileOperation as err:
            logger.warning(f"Loading error: path too long {log_prefix}: {err}", exc_info=True)
            raise InvalidPathError() from err
        except Exception as err:
            logger.error(f"Неизвестная ошибка в create_file. {log_prefix}: {err}", exc_info=True)
            raise Exception from err

    def generate_download_url(self, file_id: UUID) -> str:
        """Генерирует URL для загрузки одного файла.

        Этот метод создает временный, безопасный URL
        для прямой загрузки из хранилища, совместимого с S3.

        :param file_id: Первичный ключ UserFile для загрузки.
        :raises DatabaseError: Если файл не найден в базе данных или
                               у пользователя нет разрешения на доступ к нему.
        :raises StorageError: Если произошла ошибка при создании предварительно подписанного URL.
        :return: URL адрес для загрузки файла.
        """
        try:
            user_file = UserFile.objects.get(id=file_id, user=self.user, object_type=FileType.FILE)
        except UserFile.DoesNotExist as e:
            logger.warning(
                f"Попытка доступа к несуществующему или чужому файлу: id={file_id}, "
                f"user={self.user}",
                exc_info=True
            )
            raise DatabaseError(
                "Запрошенный файл не найден или у вас нет прав на его скачивание."
            ) from e

        s3_key: str = user_file.file.name

        if not self.s3_client.check_files_exist((user_file,)):
            logger.warning(
                f"User: '{user_file.user}. File does not found in s3/minio storage'",
                exc_info=True
            )
            raise StorageError(f"Файл: '{user_file.name}' не найден")

        try:
            presigned_url: str = self.s3_client.s3_public_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': settings.AWS_STORAGE_BUCKET_NAME,
                    'Key': s3_key,
                    'ResponseContentDisposition': f'attachment; filename="{user_file.name}"'
                },
                ExpiresIn=PRESIGNED_URL_LIFETIME_SECONDS  # Длительность жизни ссылки
            )
        except ParamValidationError as e:
            logger.error(f"{e}", exc_info=True)
            raise StorageError(f"Произошла ошибка при формировании ссылки "
                               f"на скачивание файла '{user_file.name}'") from e

        logger.info(
            f"File downloaded successfully. s3_key: {s3_key}, presigned_url: {presigned_url}")

        # --- НАЧАЛО ВРЕМЕННОГО КОДА ДЛЯ ОТЛАДКИ ---

        # Создаем конфигурацию прямо здесь и сейчас
        s3_config = Config(
            signature_version=settings.AWS_S3_SIGNATURE_VERSION,
            s3={'addressing_style': 'path'}
        )

        # Создаем boto3 клиент С ПРАВИЛЬНЫМ ПУБЛИЧНЫМ endpoint'ом
        public_s3_client = boto3.client(
            's3',
            endpoint_url=f"http://{settings.AWS_S3_CUSTOM_DOMAIN}",  # <--- Используем публичный URL
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_S3_REGION_NAME,
            config=s3_config,
        )

        # Генерируем URL
        presigned_url = public_s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': settings.AWS_STORAGE_BUCKET_NAME,
                'Key': s3_key,
                'ResponseContentDisposition': f'attachment; filename="{user_file.name}"'
            },
            ExpiresIn=3600
        )
        logger.info(
            f"File downloaded successfully. s3_key: {s3_key}, presigned_url_test2: {presigned_url}")
        # --- КОНЕЦ ВРЕМЕННОГО КОДА ДЛЯ ОТЛАДКИ ---
        return presigned_url
