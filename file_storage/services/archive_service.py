import logging
from typing import Iterator

from botocore.exceptions import ClientError
from django.db.models import QuerySet
from zipstream import ZipStream, ZIP_DEFLATED

from cloud_file_storage import settings
from file_storage.exceptions import StorageError
from file_storage.models import FileType, UserFile
from file_storage.storages.minio import minio_client

logger = logging.getLogger(__name__)

READ_CHUNK_SIZE = 64 * 1024 * 1024  # 64 МБ


class ZipStreamGenerator:
    """
    Генератор для создания ZIP-архива по частям (потоково).

    Предназначен для формирования ZIP-архива из файлов, хранящихся в S3-совместимом
    хранилище (Minio), без необходимости загружать все содержимое архива в память.
    """

    def __init__(self, root_directory: UserFile, all_files: QuerySet[UserFile] | None = None):
        """
        Инициализирует генератор ZIP-архива.

        :param root_directory: Корневая директория (объект UserFile), которая будет
                               корнем создаваемого ZIP-архива. Имя этой директории
                               используется как имя корневой папки в архиве.
        :param all_files: QuerySet объектов UserFile, представляющих все файлы и
                          подпапки, которые должны быть включены в архив.
        """
        self.directory = root_directory
        self.all_files: QuerySet[UserFile] | None = all_files
        self.file_size = None

    def _get_zip_path(self, file_obj: UserFile) -> str:
        """
        Формирует относительный путь для файла или папки внутри ZIP-архива.

        Путь строится относительно корневой директории архива, имя которой
        берется из `self.directory.name`.

        :param file_obj: Объект UserFile (файл или папка).
        :returns: Строка с относительным путем для объекта в ZIP-архиве.
        """

        relative_path = file_obj.path.replace(self.directory.path, '', 1)

        if relative_path.startswith('/'):
            relative_path = relative_path[1:]

        return f"{self.directory.name}/{relative_path}"

    def _stream_file_from_s3(self, s3_key: str) -> Iterator[bytes]:
        """
        Осуществляет потоковое чтение файла из S3-совместимого хранилища.

        Открывает соединение с S3, получает объект и возвращает итератор,
        который по частям (чанками) считывает тело ответа.

        :param s3_key: Ключ (путь) объекта в S3-бакете.
        :yields: Части (байтовые строки) файла.
        :raises StorageError: Если возникает проблема при доступе к S3 (например, файл не найден, нет прав).
                               Это исключение должно быть возбуждено minio_client или обработчиком ответа.
        """
        try:
            response: dict = minio_client.s3_client.get_object(
                Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                Key=s3_key,
            )
        except ClientError as e:
            raise StorageError(f"Доступ к файлу '{s3_key}' запрещен.") from e

        self.file_size = response.get('ContentLength', None)

        for chunk in iter(lambda: response['Body'].read(READ_CHUNK_SIZE), b''):
            yield chunk

    def generate(self) -> Iterator[bytes]:
        """Генерирует ZIP-архив по частям"""
        zs = ZipStream(compress_type=ZIP_DEFLATED)

        for file_obj in self.all_files:
            zip_path = self._get_zip_path(file_obj)

            if file_obj.object_type == FileType.DIRECTORY:
                zs.add(
                    data=b'',
                    arcname=zip_path,
                )
                logger.info(f"Added directory: '{file_obj.name}' to path: {zip_path}")

            elif file_obj.object_type == FileType.FILE:
                s3_key: str = file_obj.file.name
                zs.add(
                    data=self._stream_file_from_s3(s3_key),
                    arcname=zip_path,
                    size=self.file_size,
                )

        for chunk in zs:
            yield chunk

        logger.info(
            f"User '{self.directory.user}' finished downloading directory '{self.directory.name}'.")
