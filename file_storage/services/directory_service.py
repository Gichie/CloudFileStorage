"""Сервис для операций, связанных с директориями."""
import logging
from typing import Iterator
from uuid import UUID

from botocore.exceptions import NoCredentialsError, ClientError, BotoCoreError
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction, router
from django.db.models import Value
from django.db.models.functions import Replace
from django.http import Http404

from cloud_file_storage import settings
from file_storage.exceptions import StorageError, NameConflictError, DatabaseError
from file_storage.forms import RenameItemForm
from file_storage.models import UserFile, FileType
from file_storage.services.archive_service import ZipStreamGenerator
from file_storage.storages.minio import minio_client

logger = logging.getLogger(__name__)

BUCKET_NAME = settings.AWS_STORAGE_BUCKET_NAME


class DirectoryService:
    """Сервисный слой для операций с файлами и директориями."""

    def __init__(self, user: User, s3_client=minio_client):
        self.user = user
        self.s3_client = s3_client

    def create(self, directory_name: str, parent_pk: str) -> None:
        """Создает новую директорию в базе данных и соответствующий маркер в S3.

        Операция выполняется в рамках транзакции базы данных. В случае ошибки
        на любом этапе (БД или S3), изменения откатываются (для БД), и
        выбрасываются соответствующие кастомные исключения.

        :param parent_pk: ID родительской директории.
        :param directory_name: Имя новой директории.

        :raises NameConflictError: Если название уже существует в текущей директории.
        :raises DatabaseError: При ошибках целостности или других проблемах с БД.
        :raises StorageError: При ошибках взаимодействия с S3 (аутентификация, клиентские ошибки).
        """
        parent_object = self.get_parent_directory(self.user, parent_pk)

        try:
            with transaction.atomic():
                if UserFile.objects.object_with_name_exists(self.user, directory_name, parent_object):
                    logger.warning(
                        f"User {self.user.username}: Directory: {directory_name} "
                        f"already exists in parent "
                        f"'{parent_object.name if parent_object else 'root'}'.",
                        exc_info=True
                    )
                    raise NameConflictError(
                        f"Файл или папка с именем '{directory_name}' "
                        f"уже существует в текущей директории.",
                        directory_name,
                        parent_object
                    )

                new_directory: UserFile | None = UserFile(
                    user=self.user,
                    name=directory_name,
                    object_type=FileType.DIRECTORY,
                    parent=parent_object,
                )
                new_directory.save()

                key = new_directory.get_s3_key_for_directory_marker()
                self.s3_client.create_empty_directory_marker(BUCKET_NAME, key)

                logger.info(
                    f"User {self.user.username} Directory successfully created in DB and S3. "
                    f"Path={key}, DB ID={new_directory.id}"
                )

        except IntegrityError as e:
            logger.error(f"Database integrity error during folder creation: {e}", exc_info=True)
            raise DatabaseError()

        except NoCredentialsError as e:
            logger.critical(f"S3/Minio credentials not found. Cannot create directory marker. {e}",
                            exc_info=True)
            raise StorageError()

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")
            logger.error(
                f"S3 ClientError while creating directory marker: {e} (Code: {error_code})",
                exc_info=True)
            raise StorageError()

        except BotoCoreError as e:
            logger.error(f"BotoCoreError while creating directory marker '{key}': {e}", exc_info=True)
            raise StorageError()

    @staticmethod
    def _update_children_paths(directory: UserFile, old_path: str, new_path: str) -> None:
        """
        Массово обновляет пути дочерних объектов в базе данных.

        Использует `UPDATE` с функцией `Replace` для выполнения операции
        одним запросом к БД.

        :param directory: Переименованная родительская директория.
        :param old_path: Старый путь (префикс), который нужно заменить.
        :param new_path: Новый путь (префикс), на который нужно заменить.
        """
        children = UserFile.objects.filter(user=directory.user, path__startswith=old_path)
        children.update(path=Replace('path', Value(old_path), Value(new_path)))
        UserFile.objects.filter(
            user=directory.user, path__startswith=new_path, object_type=FileType.FILE
        ).update(file=Replace('file', Value(old_path), Value(new_path)))

    def rename(self, object_instance: UserFile, form: RenameItemForm) -> None:
        """
        Обрабатывает процесс переименования объекта в БД и в S3/Minio.

        Операция выполняется в рамках одной транзакции БД.
        1. Сохраняет новое имя в БД.
        2. Формирует старый и новый ключи для S3/Minio.
        3. Вызывает соответствующий метод клиента Minio для переименования
           файла или "папки" (обновления префиксов).
        4. Для папок, обновляет пути всех дочерних объектов в БД.

        :param object_instance: Экземпляр UserFile до изменения.
        :param form: Валидная форма с новыми данными.
        """
        with transaction.atomic():
            if object_instance.object_type == FileType.FILE:
                old_minio_key: str = object_instance.file.name
            else:
                old_minio_key = object_instance.path

            form.save()
            new_minio_key = object_instance.get_full_path()

            if object_instance.object_type == FileType.FILE:
                self.s3_client.rename_file(old_minio_key, new_minio_key)

            else:
                if old_minio_key and new_minio_key and old_minio_key != new_minio_key:
                    self._update_children_paths(
                        object_instance, old_minio_key, new_minio_key
                    )
                minio_client.rename_directory(old_minio_key, new_minio_key)

    def delete_obj(self, storage_object: UserFile) -> None:
        """
        Удаляет объект (файл или папку) из БД и S3-хранилища.

        Если объект - файл, он удаляется из БД и из S3 автоматически.
        Если объект - папка, сначала удаляются все вложенные объекты из БД,
        затем все связанные с ними файлы из S3 по префиксу.

        :param storage_object: Экземпляр модели UserFile для удаления.
        """
        logger.info(
            f"User: '{storage_object.user}' "
            f"is trying to delete {storage_object.object_type}: '{storage_object}' "
            f"with ID: {storage_object.id}"
        )
        if storage_object.object_type == FileType.FILE:
            storage_object.delete()

        else:
            with transaction.atomic():
                # delete from db
                files_to_delete = UserFile.objects.get_all_children_files(storage_object)
                files_to_delete._raw_delete(using=router.db_for_write(UserFile))

                # delete from s3
                prefix = storage_object.path
                self.s3_client.delete_objects_by_prefix(prefix)

        logger.info(
            f"User: '{storage_object.user}' deleted {storage_object.object_type} from DB successful")

    def get_parent_or_create_directories_from_path(self, parent_object, path_components):
        """Создает иерархию директорий по указанному пути."""
        current_parent = parent_object

        for directory_name in path_components:
            directory_object, created = UserFile.objects.get_or_create(
                user=self.user,
                name=directory_name,
                parent=current_parent,
                object_type=FileType.DIRECTORY,
            )

            if created:
                logger.debug(
                    f"User '{self.user.username}': Created directory '{directory_name}' "
                    f"(ID: {directory_object.id}) under parent "
                    f"'{current_parent.name if current_parent else 'root'}'."
                )
                try:
                    # Создание "директории" в S3/Minio
                    key = directory_object.get_s3_key_for_directory_marker()
                    self.s3_client.create_empty_directory_marker(BUCKET_NAME, key)
                    logger.debug(
                        f"User '{self.user.username}': S3 marker created for directory '{key}'.")
                except (NoCredentialsError, ClientError, BotoCoreError) as e:
                    logger.error(
                        f"User '{self.user.username}': FAILED to create S3 marker "
                        f"for directory '{directory_object.name}' "
                        f"(ID: {directory_object.id}). Error: {e}",
                        exc_info=True
                    )
                    raise StorageError(f"Ошибка создания папки {directory_name} в S3 хранилище.") from e

            current_parent = directory_object
        return current_parent

    def get_parent_directory(self, parent_pk: str | int | None) -> UserFile | None:
        """Получает родительскую директорию по её первичному ключу.

        Проверяет, что директория принадлежит указанному пользователю и
        имеет тип "директория".

        :param parent_pk: Первичный ключ родительской директории. Может быть ``None``,
                          если создается объект в корневой директории пользователя.
                          Может быть строкой (из POST) или числом.
        :return: Объект ``UserFile``, представляющий родительскую директорию, или ``None``,
                 если ``parent_pk`` не указан (означает корень).
        :raises UserFile.DoesNotExist: Если директория с указанным ``parent_pk`` не найдена,
                                       не принадлежит пользователю, или не является директорией.
        :raises ValueError: Если ``parent_pk`` имеет некорректный формат для запроса к БД.
        :raises TypeError: Если ``parent_pk`` имеет некорректный тип для запроса к БД.
        """
        if parent_pk:
            try:
                parent_object: UserFile = UserFile.objects.get(
                    pk=parent_pk,
                    user=self.user,
                    object_type=FileType.DIRECTORY,
                )
                logger.info(
                    f"User: '{self.user.username}' "
                    f"successfully identified parent directory: '{parent_object.name}' "
                    f"(ID: {parent_object.id}) for new directory creation."
                )

                return parent_object

            except UserFile.DoesNotExist:
                logger.warning(
                    f"Parent directory not found. pk={parent_pk} user={self.user} ID: {self.user.id} "
                    f"Requested parent_pk: '{parent_pk}'. "
                    f"Query was for object_type: {FileType.DIRECTORY}.",
                    exc_info=True
                )
                raise

            except (ValueError, TypeError):
                logger.error(
                    f"User={self.user.username} ID: {self.user.id} "
                    f"object_type={FileType.DIRECTORY} Invalid parent folder identifier. "
                    f"pk={parent_pk}",
                    exc_info=True
                )
                raise

            except Exception as e:
                logger.error(f"Unexpected error. User: {self.user}. {e}")
                raise

    def get_current_directory_from_path(self, unencoded_path: str) -> UserFile | None:
        """
        Возвращает объект директории на основе предоставленного пути.

        Если путь пустой, возвращает ``None``, что означает корневую директорию пользователя.
        Выполняет поиск директории в базе данных по пользователю,
        нормализованному пути и типу "директория".

        :param unencoded_path: Строка пути, не кодированная для URL.
        :raises Http404: Если директория не найдена или найдено несколько директорий.
        :return: Объект ``UserFile``, представляющий текущую директорию, или ``None``, если путь пустой
                 (что интерпретируется как корневой уровень пользователя).
        """
        current_directory: UserFile | None = None

        if unencoded_path:
            path_components = [comp for comp in unencoded_path.split('/') if
                               comp and comp not in ['.', '..']]
            safe_path = '/'.join(path_components)

            if path_components:
                name_part = path_components[-1]
                path = f"user_{self.user.id}/{safe_path}/"

                if path:
                    try:
                        current_directory = UserFile.objects.get(
                            user=self.user,
                            path=path,
                            object_type=FileType.DIRECTORY,
                        )

                    except UserFile.DoesNotExist:
                        logger.warning(
                            f"User '{self.user.username}': "
                            f"Directory not found for path component '{name_part}' "
                            f"Full requested path: '{unencoded_path}'. Raising Http404."
                        )
                        raise Http404("Запрошенная директория не найдена или не является директорией.")
                    except UserFile.MultipleObjectsReturned:
                        logger.error(
                            f"User '{self.user.username}': "
                            f"Multiple objects returned for path component '{name_part}' "
                            f"Full requested path: '{unencoded_path}'. "
                            f"This indicates a data integrity issue. Raising Http404."
                        )
                        raise Http404("Ошибка при поиске директории (найдено несколько объектов).")

        return current_directory

    def _update_children_path(self, storage_item: UserFile) -> None:
        """
        Рекурсивно обновляет поле `path` для самого объекта и всех его дочерних элементов.

        Сохраняет текущий элемент, чтобы сгенерировать новый путь на основе
        нового родителя, а затем рекурсивно вызывает себя для всех дочерних
        элементов, если текущий элемент - папка.

        :param storage_item: Экземпляр UserFile, для которого нужно обновить путь.
        """
        storage_item.save()

        if storage_item.object_type == FileType.DIRECTORY:
            for child in storage_item.children.iterator():
                self._update_children_path(child)

    def move(self, item_id: str, destination_folder_id: str) -> None:
        """
        Выполняет операцию перемещения файла или папки.

        Находит перемещаемый объект и папку назначения по их ID, проверяя
        принадлежность пользователю. Проверяет конфликт имен, затем выполняет
        перемещение в базе данных и в S3-хранилище в рамках одной транзакции.

        :param item_id: ID объекта (UserFile), который нужно переместить.
        :param destination_folder_id: ID папки назначения.
        :raises NameConflictError: Если в папке назначения уже существует
                                   объект с таким же именем.
        """
        storage_item = UserFile.objects.get(user=self.user, id=item_id)
        old_key = storage_item.path

        if destination_folder_id:
            destination_folder = UserFile.objects.get(
                user=self.user, id=destination_folder_id, object_type=FileType.DIRECTORY
            )
        else:
            destination_folder = None

        if UserFile.objects.file_exists(storage_item.user, destination_folder, storage_item.name):
            raise NameConflictError(
                f"Файл или папка с именем '{storage_item.name}' уже существует "
                f"в папке '{destination_folder}'",
                storage_item.name,
                destination_folder,
            )

        storage_item.parent = destination_folder

        with transaction.atomic():
            self._update_children_path(storage_item)
            new_key = storage_item.path
            self.s3_client.move_object(old_key, new_key)

    def download(self, directory_id: UUID) -> tuple[Iterator[bytes], str]:
        """Создает поток данных ZIP-архива и его имя для указанной директории.

        Метод координирует процесс создания ZIP-архива для директории пользователя.
        Он выполняет проверку прав доступа, убеждается в наличии всех дочерних
        файлов в S3-хранилище и инициализирует генератор для потоковой передачи
        данных, чтобы избежать загрузки всего архива в оперативную память сервера.

        :param directory_id: UUID директории, которую необходимо заархивировать.
        :raises DatabaseError: Если директория с указанным ``directory_id`` не найдена
                               в базе данных или не принадлежит указанному ``user``.
        :raises StorageError: Если один или несколько дочерних файлов директории
                              отсутствуют в S3-совместимом хранилище.
        :return: Кортеж, содержащий два элемента:
                 1. Итератор с байтами ZIP-архива.
                 2. Сгенерированное имя файла для этого архива (например, 'MyFolder.zip').
        """
        try:
            directory: UserFile = UserFile.objects.get(
                id=directory_id, user=self.user, object_type=FileType.DIRECTORY
            )
        except UserFile.DoesNotExist:
            logger.warning(
                f"Попытка доступа к несуществующей или чужой папке: id={directory_id}, "
                f"user={self.user}",
                exc_info=True
            )
            raise DatabaseError(
                "Запрошенная папка не найдена или у вас нет прав на её скачивание."
            )

        all_files = UserFile.objects.get_all_children_files(directory)

        if not self.s3_client.check_files_exist(all_files):
            raise StorageError("Ошибка. Не удалось прочитать некоторые файлы из хранилища")

        zip_generator = ZipStreamGenerator(directory, all_files)
        zip_filename = f"{directory.name}.zip"

        zip_stream = zip_generator.generate()

        logger.info(f"User '{self.user.username}' started "
                    f"downloading directory '{directory.name}' "
                    f"as '{zip_filename}'.")
        return zip_stream, zip_filename
