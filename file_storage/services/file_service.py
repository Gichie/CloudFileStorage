import logging
from uuid import UUID

from botocore.exceptions import ParamValidationError
from django.contrib.auth.models import User
from django.core.exceptions import SuspiciousFileOperation

from cloud_file_storage import settings
from cloud_file_storage.settings import PRESIGNED_URL_LIFETIME_SECONDS
from file_storage.exceptions import NameConflictError, InvalidPathError, DatabaseError, StorageError
from file_storage.models import UserFile, FileType
from file_storage.storages.minio import minio_client, MinioClient

logger = logging.getLogger(__name__)


class FileService:
    def __init__(self, user: User, s3_client: MinioClient = minio_client):
        self.user = user
        self.s3_client = s3_client

    def create_file(self, uploaded_file, parent_object, log_prefix=None):
        if UserFile.objects.file_exists(self.user, parent_object, uploaded_file.name):
            message = f"Upload failed. File or directory with this name already exists. {log_prefix}"
            logger.error(message, exc_info=True)
            raise NameConflictError('Такой файл уже существует', uploaded_file.name, parent_object.name)

        try:
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

        except SuspiciousFileOperation as e:
            logger.warning(f"Loading error: path too long {log_prefix}: {e}", exc_info=True)
            raise InvalidPathError()

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
        except UserFile.DoesNotExist:
            logger.warning(
                f"Попытка доступа к несуществующему или чужому файлу: id={file_id}, "
                f"user={self.user}",
                exc_info=True
            )
            raise DatabaseError(f"Запрошенный файл не найден или у вас нет прав на его скачивание.")

        s3_key: str = user_file.file.name

        if not self.s3_client.check_files_exist((user_file,)):
            logger.warning(
                f"User: '{user_file.user}. File does not found in s3/minio storage'",
                exc_info=True
            )
            raise StorageError(f"Файл: '{user_file.name}' не найден")

        try:
            presigned_url: str = self.s3_client.s3_client.generate_presigned_url(
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
                               f"на скачивание файла '{user_file.name}'")

        logger.info(
            f"File downloaded successfully. s3_key: {s3_key}, presigned_url: {presigned_url}")

        return presigned_url
