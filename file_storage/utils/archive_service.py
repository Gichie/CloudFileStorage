import io
import logging
import zipfile
from typing import Iterator

from botocore.exceptions import ClientError

from cloud_file_storage import settings
from file_storage.models import UserFile, FileType
from file_storage.utils.minio import get_s3_client

logger = logging.getLogger(__name__)

READ_CHUNK_SIZE = 32 * 1024 * 1024  # 32 МБ


class ZipStreamGenerator:
    """Генератор для создания ZIP-архива"""

    def __init__(self, root_directory):
        self.directory = root_directory
        self.s3_client = get_s3_client()

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
        ).select_related().order_by('path', 'name'))

        return all_files

    def _stream_file_from_s3(self, s3_key: str) -> Iterator[bytes]:
        """Потоковое чтение файла из S3"""
        try:
            response = self.s3_client.get_object(
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

        # Создаем временный буфер
        buffer = io.BytesIO()

        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            all_files = self._get_all_files(self.directory)

            for file_obj in all_files:
                zip_path = self._get_zip_path(file_obj)
                zip_info = zipfile.ZipInfo(zip_path)
                zip_info.compress_type = zipfile.ZIP_DEFLATED

                if file_obj.object_type == FileType.DIRECTORY:
                    zip_file.writestr(zip_info, b'')
                    logger.info(f"Added directory: '{file_obj.name}' to path: {zip_path}")

                elif file_obj.object_type == FileType.FILE:
                    s3_key = file_obj.file.name

                    try:
                        head_response = self.s3_client.head_object(
                            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                            Key=s3_key,
                        )
                        file_size = head_response['ContentLength']
                        zip_info.file_size = file_size

                        with zip_file.open(zip_info, 'w') as zip_entry:
                            for chunk in self._stream_file_from_s3(s3_key):
                                zip_entry.write(chunk)

                        logger.info(f"Added file: '{file_obj.name}' ({file_size} bytes) to path: {zip_path}")

                    except ClientError as e:
                        logger.error(f"Error processing file: '{file_obj.name}' "
                                     f"to path: {zip_path} S3 Key: '{s3_key}' {e}")
                        zip_file.writestr(zip_path, b'')

        buffer.seek(0)
        while True:
            chunk = buffer.read(READ_CHUNK_SIZE)
            if not chunk:
                logger.info(f"User '{self.directory.user}' downloaded directory")
                break
            yield chunk
