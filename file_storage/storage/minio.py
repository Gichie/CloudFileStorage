import io
import logging

import boto3
from botocore.exceptions import ClientError

from cloud_file_storage import settings
from file_storage.models import FileType

logger = logging.getLogger(__name__)


class MinioStorage:
    def __init__(self):
        self._s3_client = None

    @property
    def s3_client(self):
        """Инициализация S3 клиента"""
        if self._s3_client is None:
            self._s3_client = boto3.client(
                's3',
                endpoint_url=settings.AWS_S3_ENDPOINT_URL,
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_S3_REGION_NAME,
            )
        return self._s3_client

    def create_empty_directory_marker(self, bucket: str, key: str):
        """
        Создаёт пустой объект в MinIO для обозначения директории.
        """
        self.s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=io.BytesIO(b'')
        )

    def check_files_exist(self, files):
        for file in files:
            if file.object_type == FileType.FILE:
                try:
                    s3_key = file.file.name
                    self.s3_client.head_object(
                        Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                        Key=s3_key,
                    )

                except ClientError as e:
                    logger.error(f"Не удалось получить метаданные файла {s3_key}: {e}")
                    return False
        return True

    def get_all_object_keys_in_folder(self, prefix):
        """Получает ВСЕ ключи объектов по заданному префиксу, используя Paginator."""
        keys_to_delete = []

        paginator = self.s3_client.get_paginator('list_objects_v2')

        pages = paginator.paginate(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Prefix=prefix)

        for page in pages:
            for obj in page.get('Contents', []):
                keys_to_delete.append({"Key": obj['Key']})

        return keys_to_delete


minio_storage = MinioStorage()
