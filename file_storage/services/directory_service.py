import logging

from botocore.exceptions import NoCredentialsError, ClientError, BotoCoreError
from django.http import JsonResponse, Http404

from cloud_file_storage import settings
from file_storage.exceptions import NameConflictError, StorageError
from file_storage.models import UserFile, FileType, User
from file_storage.storage.minio import minio_storage

logger = logging.getLogger(__name__)


def get_parent_directory_or_json_response(user, parent_pk):
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
                f"[{__name__}] User '{user.username}' "
                f"successfully identified parent directory: '{parent_object.name}' "
                f"(ID: {parent_object.id}) for new directory creation."
            )
            return parent_object

        except UserFile.DoesNotExist:
            logger.warning(
                f"Parent directory not found. pk={parent_pk} user={user.username} ID: {user.id} "
                f"Requested parent_pk: '{parent_pk}'. Query was for object_type: {FileType.DIRECTORY}"
            )
            return JsonResponse(
                {'status': 'error', 'message': 'Родительская папка не найдена'},
                status=400,
            )
        except (ValueError, TypeError):
            logger.error(
                f"User={user.username} ID: {user.id} "
                f"object_type={FileType.DIRECTORY} Invalid parent folder identifier. pk={parent_pk}",
                exc_info=True
            )
            return JsonResponse(
                {'status': 'error', 'message': 'Некорректный идентификатор родительской папки.'},
                status=400
            )
    return None


def directory_exists(user, directory_name, parent_object):
    """
    Проверяет существование директории с указанным именем в родительской директории
    """
    return UserFile.objects.filter(
        user=user,
        name=directory_name,
        parent=parent_object,
    ).exists()


def create_directories_from_path(user, parent_object, path_components):
    """
    Создает иерархию директорий по указанному пути
    """
    current_parent = parent_object

    for directory_name in path_components:
        if UserFile.objects.filter(
                user=user,
                name=directory_name,
                parent=current_parent,
                object_type=FileType.FILE
        ).exists():
            message = (f"Upload failed. File with this name already exists. User: {user}. "
                       f"Name: {directory_name}, parent: {current_parent}")
            logger.warning(message)
            raise NameConflictError(message, directory_name, current_parent)

        directory_object, created = UserFile.objects.get_or_create(
            user=user,
            name=directory_name,
            parent=current_parent,
            object_type=FileType.DIRECTORY,
        )

        if created:
            logger.info(
                f"User '{user.username}': Created directory '{directory_name}' "
                f"(ID: {directory_object.id}) under parent "
                f"'{current_parent.name if current_parent else 'root'}'."
            )
            try:
                # Создание "директории" в S3/Minio
                key = directory_object.get_s3_key_for_directory_marker()
                minio_storage.create_empty_directory_marker(settings.AWS_STORAGE_BUCKET_NAME, key)
                logger.info(f"User '{user.username}': S3 marker created for directory '{key}'.")
            except (NoCredentialsError, ClientError, BotoCoreError) as e:
                logger.error(
                    f"User '{user.username}': FAILED to create S3 marker for directory '{directory_object.name}' "
                    f"(ID: {directory_object.id}). Error: {e}",
                    exc_info=True
                )
                raise StorageError(f"Ошибка создания папки {directory_name} в S3 хранилище.") from e

        current_parent = directory_object
    return current_parent


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
