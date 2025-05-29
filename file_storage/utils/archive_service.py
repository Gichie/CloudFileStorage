import logging
from typing import Iterator

from botocore.exceptions import ClientError
from zipstream import ZipStream, ZIP_DEFLATED

from cloud_file_storage import settings
from file_storage.models import UserFile, FileType
from file_storage.utils.minio import minio_storage

logger = logging.getLogger(__name__)

READ_CHUNK_SIZE = 64 * 1024 * 1024  # 64 МБ


class ZipStreamGenerator:
    """Генератор для создания ZIP-архива"""

    def __init__(self, root_directory):
        self.directory = root_directory

    def _get_zip_path(self, file_obj) -> str:
        """Получает путь файла внутри ZIP"""

        relative_path = file_obj.path.replace(self.directory.path, '', 1)

        if relative_path.startswith('/'):
            relative_path = relative_path[1:]

        return f"{self.directory.name}/{relative_path}"

    def _get_all_files(self, directory):
        """
        Получает все файлы рекурсивно одним запросом
        """

        all_files = (UserFile.objects.filter(
            user=directory.user, path__startswith=directory.path
        ).exclude(
            id=directory.id
        ).select_related('user').only(
            'id', 'name', 'path', 'object_type', 'file', 'user__id'
        ).order_by('path', 'name'))

        return all_files

    def _stream_file_from_s3(self, s3_key: str) -> Iterator[bytes]:
        """Потоковое чтение файла из S3"""
        try:
            response = minio_storage.s3_client.get_object(
                Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                Key=s3_key,
            )

            for chunk in iter(lambda: response['Body'].read(READ_CHUNK_SIZE), b''):
                yield chunk

        except ClientError as e:
            logger.error(f"Error streaming file {s3_key} from S3: {e}")
            yield b''

    def generate(self) -> Iterator[bytes]:
        """Генерирует ZIP-архив по частям"""
        zs = ZipStream(compress_type=ZIP_DEFLATED)
        all_files = self._get_all_files(self.directory)

        for file_obj in all_files:
            zip_path = self._get_zip_path(file_obj)

            if file_obj.object_type == FileType.DIRECTORY:
                zs.add(
                    data=b'',
                    arcname=zip_path,
                )
                logger.info(f"Added directory: '{file_obj.name}' to path: {zip_path}")

            elif file_obj.object_type == FileType.FILE:
                s3_key = file_obj.file.name
                file_size = None
                try:
                    head_response = minio_storage.s3_client.head_object(
                        Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                        Key=s3_key,
                    )
                    file_size = head_response['ContentLength']
                except ClientError as e:
                    logger.warning(
                        f"Could not get ContentLength for S3 object {s3_key}. "
                        f"File will be added to ZIP without pre-defined size. Error: {e}"
                    )

                zs.add(
                    data=self._stream_file_from_s3(s3_key),
                    arcname=zip_path,
                    size=file_size,
                )

        for chunk in zs:
            yield chunk

        logger.info(f"User '{self.directory.user}' finished downloading directory '{self.directory.name}'.")
