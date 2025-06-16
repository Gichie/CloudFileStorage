import io
import logging

import boto3
from botocore.exceptions import ClientError

from cloud_file_storage import settings
from file_storage.exceptions import StorageError
from file_storage.models import FileType

logger = logging.getLogger(__name__)

BUCKET_NAME = settings.AWS_STORAGE_BUCKET_NAME


class MinioClient:
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
        keys_in_folder = []

        try:
            paginator = self.s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Prefix=prefix)
        except Exception as e:
            raise StorageError(f"{e}")

        for page in pages:
            for obj in page.get('Contents', []):
                keys_in_folder.append({"Key": obj['Key']})

        return keys_in_folder

    def delete_file(self, key):
        try:
            self.s3_client.delete_object(Bucket=BUCKET_NAME, Key=key)
            logger.debug(f"Deleted old file '{key}'")

        except Exception as e:
            logger.error(f"Error while deleting the file to the repository from {key}'. {e}", exc_info=True)
            raise StorageError

    def delete_objects_by_prefix(self, prefix):
        objects_to_delete = self.get_all_object_keys_in_folder(prefix)
        if not objects_to_delete:
            logger.info(f"Directory '{prefix}' empty or does not exists.")

        chunk_size = 1000
        for i in range(0, len(objects_to_delete), chunk_size):
            chunk = objects_to_delete[i:i + chunk_size]

            delete_request = {'Objects': chunk}

            self.s3_client.delete_objects(Bucket=BUCKET_NAME, Delete=delete_request)
            logger.info(f"{len(chunk)} objects removed")

    def rename_file(self, old_key, new_key):
        try:
            self.s3_client.copy_object(
                Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                CopySource={'Bucket': BUCKET_NAME, 'Key': old_key},
                Key=new_key
            )
            logger.debug(f"Copied '{old_key}' to '{new_key}'")

        except Exception as e:
            logger.error(f"Error while copying the file to the repository from '{old_key}' to '{new_key}'. {e}",
                         exc_info=True)
            raise StorageError

        self.delete_file(old_key)

    def rename_directory(self, old_minio_prefix, new_minio_prefix):
        objects_to_rename = self.get_all_object_keys_in_folder(old_minio_prefix)
        for obj in objects_to_rename:
            old_key = obj.get("Key", '')
            if old_key.startswith(old_minio_prefix):
                new_key = f"{new_minio_prefix}{old_key[len(old_minio_prefix):]}"

                if old_key == new_key:
                    logger.info(
                        f"Old key and new key are identical '{old_key}'. Skipping rename operation for this object.")
                    continue

                try:
                    self.rename_file(old_key, new_key)
                except Exception as e:
                    logger.error(f"Error renaming object from '{old_key}' to '{new_key}': {e}",
                                 exc_info=True)


minio_client = MinioClient()
