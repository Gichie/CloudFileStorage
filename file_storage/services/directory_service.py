import logging

from botocore.exceptions import NoCredentialsError, ClientError, BotoCoreError
from django.db import IntegrityError, transaction, router
from django.db.models import Value
from django.db.models.functions import Replace
from django.http import Http404, JsonResponse

from cloud_file_storage import settings
from file_storage.exceptions import StorageError, ParentDirectoryNotFoundError, InvalidParentIdError, NameConflictError
from file_storage.models import UserFile, FileType, User
from file_storage.storages.minio import minio_client

logger = logging.getLogger(__name__)

BUCKET_NAME = settings.AWS_STORAGE_BUCKET_NAME


class DirectoryService:
    @staticmethod
    def create(user, directory_name, parent_object=None):
        """
        Создает запись директории в БД и вызывает создание маркера для обозначения директории в S3 хранилище
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
                minio_client.create_empty_directory_marker(BUCKET_NAME, key)

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

    @staticmethod
    def update_children_paths(directory, old_path, new_path):
        children = UserFile.objects.filter(user=directory.user, path__startswith=old_path)
        children.update(path=Replace('path', Value(old_path), Value(new_path)))
        UserFile.objects.filter(
            user=directory.user, path__startswith=new_path, object_type=FileType.FILE
        ).update(file=Replace('file', Value(old_path), Value(new_path)))

    @staticmethod
    def delete_obj(storage_object):
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
                minio_client.delete_objects_by_prefix(prefix)

        logger.info(f"User: '{storage_object.user}' deleted {storage_object.object_type} from DB successful")

    @staticmethod
    def get_parent_or_create_directories_from_path(user, parent_object, path_components):
        """
        Создает иерархию директорий по указанному пути
        """
        current_parent = parent_object

        for directory_name in path_components:
            directory_object, created = UserFile.objects.get_or_create(
                user=user,
                name=directory_name,
                parent=current_parent,
                object_type=FileType.DIRECTORY,
            )

            if created:
                logger.debug(
                    f"User '{user.username}': Created directory '{directory_name}' "
                    f"(ID: {directory_object.id}) under parent "
                    f"'{current_parent.name if current_parent else 'root'}'."
                )
                try:
                    # Создание "директории" в S3/Minio
                    key = directory_object.get_s3_key_for_directory_marker()
                    minio_client.create_empty_directory_marker(BUCKET_NAME, key)
                    logger.debug(f"User '{user.username}': S3 marker created for directory '{key}'.")
                except (NoCredentialsError, ClientError, BotoCoreError) as e:
                    logger.error(
                        f"User '{user.username}': FAILED to create S3 marker for directory '{directory_object.name}' "
                        f"(ID: {directory_object.id}). Error: {e}",
                        exc_info=True
                    )
                    raise StorageError(f"Ошибка создания папки {directory_name} в S3 хранилище.") from e

            current_parent = directory_object
        return current_parent

    @staticmethod
    def get_parent_directory(user, parent_pk):
        """
        Получает родительскую директорию по ID с проверкой прав доступа
        """
        if parent_pk:
            try:
                parent_object = UserFile.objects.get(
                    pk=parent_pk,
                    user=user,
                    object_type=FileType.DIRECTORY,
                )
                logger.info(
                    f"User: '{user.username}' "
                    f"successfully identified parent directory: '{parent_object.name}' "
                    f"(ID: {parent_object.id}) for new directory creation."
                )
                return parent_object

            except UserFile.DoesNotExist:
                logger.warning(
                    f"Parent directory not found. pk={parent_pk} user={user.username} ID: {user.id} "
                    f"Requested parent_pk: '{parent_pk}'. Query was for object_type: {FileType.DIRECTORY}",
                    exc_info=True
                )
                raise ParentDirectoryNotFoundError

            except (ValueError, TypeError):
                logger.error(
                    f"User={user.username} ID: {user.id} "
                    f"object_type={FileType.DIRECTORY} Invalid parent folder identifier. pk={parent_pk}",
                    exc_info=True
                )
                raise InvalidParentIdError

        return None

    @staticmethod
    def get_current_directory_from_path(user: User, unencoded_path: str) -> UserFile | None:
        """
        Возвращает объект директории
        """
        current_directory = None

        if unencoded_path:
            path_components = [comp for comp in unencoded_path.split('/') if comp and comp not in ['.', '..']]

            if path_components:
                name_part = path_components[-1]
                path = f"user_{user.id}/{unencoded_path}/"

                if path:
                    try:
                        current_directory = UserFile.objects.get(
                            user=user,
                            path=path,
                            object_type=FileType.DIRECTORY,
                        )

                    except UserFile.DoesNotExist:
                        logger.warning(
                            f"User '{user.username}': Directory not found for path component '{name_part}' "
                            f"Full requested path: '{unencoded_path}'. Raising Http404."
                        )
                        raise Http404("Запрошенная директория не найдена или не является директорией.")
                    except UserFile.MultipleObjectsReturned:
                        logger.error(
                            f"User '{user.username}': Multiple objects returned for path component '{name_part}' "
                            f"Full requested path: '{unencoded_path}'. "
                            f"This indicates a data integrity issue. Raising Http404."
                        )
                        raise Http404("Ошибка при поиске директории (найдено несколько объектов).")

        return current_directory

    @staticmethod
    def _update_children_path(storage_item):
        storage_item.save()

        if storage_item.object_type == FileType.DIRECTORY:
            for child in storage_item.children.iterator():
                DirectoryService._update_children_path(child)

    @staticmethod
    def move(storage_item, destination_folder=None):
        if UserFile.objects.file_exists(storage_item.user, destination_folder, storage_item.name):
            raise NameConflictError(
                "Файл или папка с таким именем уже существует",
                storage_item.name,
                destination_folder,
            )
        storage_item.parent = destination_folder

        DirectoryService._update_children_path(storage_item)
