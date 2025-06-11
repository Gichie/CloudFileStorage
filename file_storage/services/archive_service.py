import logging
from typing import Iterator

from zipstream import ZipStream, ZIP_DEFLATED

from cloud_file_storage import settings
from file_storage.models import FileType
from file_storage.storage.minio import minio_storage

logger = logging.getLogger(__name__)

READ_CHUNK_SIZE = 64 * 1024 * 1024  # 64 МБ


class ZipStreamGenerator:
    """Генератор для создания ZIP-архива"""

    def __init__(self, root_directory, all_files=None):
        self.directory = root_directory
        self.all_files = all_files
        self.file_size = None

    def _get_zip_path(self, file_obj) -> str:
        """Получает путь файла внутри ZIP"""

        relative_path = file_obj.path.replace(self.directory.path, '', 1)

        if relative_path.startswith('/'):
            relative_path = relative_path[1:]

        return f"{self.directory.name}/{relative_path}"

    def _stream_file_from_s3(self, s3_key: str) -> Iterator[bytes]:
        """Потоковое чтение файла из S3"""
        response = minio_storage.s3_client.get_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=s3_key,
        )

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
                s3_key = file_obj.file.name
                zs.add(
                    data=self._stream_file_from_s3(s3_key),
                    arcname=zip_path,
                    size=self.file_size,
                )

        for chunk in zs:
            yield chunk

        logger.info(f"User '{self.directory.user}' finished downloading directory '{self.directory.name}'.")
