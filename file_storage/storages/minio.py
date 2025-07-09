import io
import logging
from collections.abc import Iterable

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from mypy_boto3_s3 import S3Client
from mypy_boto3_s3.type_defs import DeleteTypeDef, ObjectIdentifierTypeDef

from cloud_file_storage import settings
from file_storage.exceptions import StorageError
from file_storage.models import FileType, UserFile

logger = logging.getLogger(__name__)


class MinioClient:
    """
    Клиент-обертка для взаимодействия с S3-совместимым хранилищем (Minio).

    Инкапсулирует логику работы с boto3, предоставляя упрощенные методы
    для конкретных операций приложения.
    Обрабатывает ошибки и ведет логирование.
    """

    def __init__(self) -> None:
        """
        Инициализирует клиент.

        Принимает готовый экземпляр boto3 клиента, что позволяет
        гибко управлять его конфигурацией и упрощает тестирование.
        """
        self._s3_client: S3Client | None = None
        self._s3_public_client: S3Client | None = None

    @property
    def s3_client(self) -> S3Client:
        """Инициализация S3 клиента."""
        s3_config = Config(
            signature_version=settings.AWS_S3_SIGNATURE_VERSION,
            # Явно указываем стиль адресации 'path', это критически важно!
            s3={'addressing_style': 'path'}
        )
        if self._s3_client is None:
            self._s3_client = boto3.client(
                's3',
                endpoint_url=settings.AWS_S3_ENDPOINT_URL,
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_S3_REGION_NAME,
                config=s3_config,
            )
        return self._s3_client

    @property
    def s3_public_client(self) -> S3Client:
        """
        S3 клиент для генерации ПУБЛИЧНЫХ URL.
        Использует внешний адрес из AWS_S3_CUSTOM_DOMAIN.
        """
        if self._s3_public_client is None:
            # Конфигурация та же самая
            s3_config = Config(
                signature_version=settings.AWS_S3_SIGNATURE_VERSION,
                s3={'addressing_style': 'path'}
            )
            self._s3_public_client = boto3.client(
                's3',
                # КЛЮЧЕВОЕ ОТЛИЧИЕ: используем ПУБЛИЧНЫЙ адрес!
                endpoint_url=f"http://{settings.AWS_S3_CUSTOM_DOMAIN}",
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_S3_REGION_NAME,
                config=s3_config,
            )
        return self._s3_public_client

    def create_empty_directory_marker(self, bucket: str, key: str) -> None:
        """Создаёт пустой объект в S3-совместимом хранилище (MinIO) для обозначения директории.

        :param bucket: Имя бакета.
        :param key: Ключ (путь) для создаваемого объекта-маркера.
        :raises BotoCoreError: Общие ошибки клиента boto.
        :raises ClientError: Ошибки со стороны сервера S3.
        """
        self.s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=io.BytesIO(b'')
        )

    def check_files_exist(self, files: Iterable[UserFile]) -> bool:
        """
        Проверяет существование файлов в S3 хранилище.

        Использует `head_object` для каждого файла, чтобы проверить его наличие
        без скачивания содержимого. Если хотя бы один файл не найден или
        произошла ошибка при проверке, возвращает False.

        :param files: Итерируемый объект экземпляров UserFile.
        :return: True, если все файлы существуют, иначе False.
        """
        for file in files:
            if file.object_type == FileType.FILE:
                try:
                    s3_key = file.file.name
                    self.s3_client.head_object(
                        Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                        Key=s3_key,
                    )

                except ClientError as e:
                    logger.error(
                        f"Не удалось получить метаданные файла '{file.name}': {e}",
                        exc_info=True
                    )
                    return False
        return True

    def get_all_object_keys_in_folder(self, prefix: str) -> list[ObjectIdentifierTypeDef]:
        """
        Получает ключи всех объектов в S3 по заданному префиксу.

        Использует Paginator для эффективной обработки любого количества объектов,
        избегая проблем с ограничением в 1000 объектов на один запрос.

        :param prefix: Префикс (путь к папке) для поиска объектов.
        :return: Список словарей, каждый из которых содержит ключ 'Key'.
        :raises StorageError: При ошибке во время взаимодействия с S3.
        """
        keys_in_folder: list[ObjectIdentifierTypeDef] = []

        try:
            paginator = self.s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Prefix=prefix)
        except Exception as e:
            raise StorageError(f"{e}") from e

        for page in pages:
            for obj in page['Contents']:
                keys_in_folder.append({"Key": obj['Key']})

        return keys_in_folder

    def delete_file(self, key: str) -> None:
        """
        Удаляет объект (файл) из бакета в Minio.

        :param key: Ключ объекта (полный путь к файлу в бакете).
        :raises StorageError: В случае, если произошла ошибка при
                              взаимодействии с API хранилища.
        """
        try:
            self.s3_client.delete_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=key)
            logger.debug(f"Deleted old file '{key}'")

        except Exception as e:
            logger.error(f"Error while deleting the file to the repository from {key}'. {e}",
                         exc_info=True)
            raise StorageError from e

    def delete_objects_by_prefix(self, prefix: str) -> None:
        """
        Удаляет все объекты в S3, ключ которых начинается с заданного префикса.

        Получает список всех ключей, подпадающих под префикс, и удаляет их
        пачками по 1000 штук.

        :param prefix: Префикс (путь к папке) для удаления объектов.
        :raises StorageError: При ошибке во время взаимодействия с S3.
        """
        objects_to_delete = self.get_all_object_keys_in_folder(prefix)
        if not objects_to_delete:
            logger.info(f"Directory '{prefix}' empty or does not exists.")
            return

        chunk_size: int = 1000
        try:
            for i in range(0, len(objects_to_delete), chunk_size):
                chunk: list[ObjectIdentifierTypeDef] = objects_to_delete[i:i + chunk_size]

                delete_request: DeleteTypeDef = {'Objects': chunk}

                self.s3_client.delete_objects(
                    Bucket=settings.AWS_STORAGE_BUCKET_NAME, Delete=delete_request
                )
                logger.info(f"{len(chunk)} objects removed")
        except ClientError as e:
            logger.error(f"Error while deleting objects by prefix: {prefix}. {e}", exc_info=True)
            raise StorageError from e
        except Exception as e:
            logger.error(f"Error while deleting objects by prefix: {prefix}. {e}", exc_info=True)
            raise StorageError from e

    def rename_file(self, old_key: str, new_key: str) -> None:
        """
        Переименовывает файл в S3/Minio.

        Так как S3 API не имеет операции "rename", она эмулируется
        через операцию "copy" с последующим "delete".

        :param old_key: Текущий ключ (путь) к файлу в хранилище.
        :param new_key: Новый ключ (путь) к файлу в хранилище.
        :raises StorageError: В случае ошибки при копировании объекта.
        """
        try:
            self.s3_client.copy_object(
                Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                CopySource={'Bucket': settings.AWS_STORAGE_BUCKET_NAME, 'Key': old_key},
                Key=new_key
            )
            logger.debug(f"Copied '{old_key}' to '{new_key}'")

        except Exception as e:
            logger.error(
                f"Error while copying the file to the repository from '{old_key}' to '{new_key}'. {e}",
                exc_info=True)
            raise StorageError from e

        self.delete_file(old_key)

    def rename_directory(self, old_minio_prefix: str, new_minio_prefix: str) -> None:
        """
        Переименовывает "папку" в S3/Minio путем копирования каждого объекта с новым ключом.

        Получает все объекты со старым префиксом, вычисляет для каждого новый ключ
        и выполняет операцию переименования файла (копирование + удаление).

        :param old_minio_prefix: Старый префикс папки.
        :param new_minio_prefix: Новый префикс папки.
        """
        objects_to_rename: list[ObjectIdentifierTypeDef] = self.get_all_object_keys_in_folder(
            old_minio_prefix)
        for obj in objects_to_rename:
            old_key = obj.get("Key", '')
            if old_key.startswith(old_minio_prefix):
                new_key = f"{new_minio_prefix}{old_key[len(old_minio_prefix):]}"

                if old_key == new_key:
                    logger.info(
                        f"Old key and new key are identical '{old_key}'. "
                        f"Skipping rename operation for this object.")
                    continue

                try:
                    self.rename_file(old_key, new_key)
                except Exception as e:
                    logger.error(f"Error renaming object from '{old_key}' to '{new_key}': {e}",
                                 exc_info=True)

    def move_object(self, old_key: str, new_key: str) -> None:
        """
        Перемещает объект в S3/Minio. Для папок вызывает rename_directory.

        Технически S3 не имеет операции "перемещения" для папок.
        Эта операция эмулируется переименованием каждого объекта внутри папки.

        :param old_key: Старый ключ (префикс) объекта или папки.
        :param new_key: Новый ключ (префикс) объекта или папки.
        """
        self.rename_directory(old_key, new_key)


minio_client = MinioClient()
