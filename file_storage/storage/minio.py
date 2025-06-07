import io
import logging

import boto3
from botocore.exceptions import NoCredentialsError, ClientError, BotoCoreError
from django.db import transaction, IntegrityError
from django.http import JsonResponse

from cloud_file_storage import settings
from file_storage.models import UserFile, FileType

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

    def create_directory(self, user, directory_name, parent_object=None):
        """
        Создает директорию в БД и S3 в рамках транзакции
        """
        try:
            with transaction.atomic():
                new_directory = UserFile(
                    user=user,
                    name=directory_name,
                    object_type=FileType.DIRECTORY,
                    parent=parent_object,
                )
                new_directory.save()

                key = new_directory.get_s3_key_for_directory_marker()
                self.create_empty_directory_marker(
                    settings.AWS_STORAGE_BUCKET_NAME,
                    key
                )

                logger.info(
                    f"User {user.username} Directory successfully created in DB and S3. "
                    f"Path={key}, DB ID={new_directory.id}"
                )

                return {'success': True, 'directory': new_directory}

        except IntegrityError as e:
            logger.error(f"Database integrity error during folder creation: {e}", exc_info=True)
            return {
                'success': False,
                'message': 'Ошибка базы данных: Не удалось создать папку из-за конфликта данных.',
                'status': 409,
            }

        except NoCredentialsError:
            logger.critical("S3/Minio credentials not found. Cannot create directory marker.", exc_info=True)
            return {
                'success': False,
                'message': 'Ошибка конфигурации сервера: Не удалось подключиться к хранилищу файлов.',
                'status': 500
            }

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")
            logger.error(f"S3 ClientError while creating directory marker '{key}': {e} (Code: {error_code})",
                         exc_info=True)
            return JsonResponse({
                'success': False,
                'message': 'Ошибка хранилища. Не удалось создать папку в облаке.'
            }, status=500)

        except BotoCoreError as e:
            logger.error(f"BotoCoreError while creating directory marker '{key}': {e}", exc_info=True)
            return {
                'success': False,
                'message': 'Произошла ошибка при взаимодействии с файловым хранилищем. Попробуйте позже.',
                'status': 503
            }

        except AttributeError as e:
            logger.error(
                f"AttributeError, possibly related to form.instance or S3 key generation: {e}", exc_info=True
            )
            return {
                'success': False,
                'message': 'Внутренняя ошибка сервера при подготовке данных для хранилища.',
                'status': 500
            }

        except Exception as e:
            logger.critical(f"Unexpected error during folder creation (S3 part): {e}", exc_info=True)
            return {
                'success': False,
                'message': 'Произошла непредвиденная ошибка при создании папки.',
                'status': 500
            }

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


minio_storage = MinioStorage()
