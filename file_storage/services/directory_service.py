import logging

from botocore.exceptions import NoCredentialsError, ClientError, BotoCoreError
from django.db import IntegrityError, transaction, router
from django.http import Http404, JsonResponse

from cloud_file_storage import settings
from file_storage.exceptions import StorageError, ParentDirectoryNotFoundError, InvalidParentIdError
from file_storage.models import UserFile, FileType, User
from file_storage.storage.minio import minio_storage
from file_storage.utils import file_utils

logger = logging.getLogger(__name__)


def create_directory(user, directory_name, parent_object=None):
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
            minio_storage.create_empty_directory_marker(
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


def delete_object(storage_object):
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
            files_to_delete = file_utils.get_all_files(storage_object)

            files_to_delete._raw_delete(using=router.db_for_write(UserFile))

            # delete from s3
            prefix = storage_object.path
            objects_to_delete = minio_storage.get_all_object_keys_in_folder(prefix)
            if not objects_to_delete:
                logger.info(f"Directory '{prefix}' empty or does not exists.")

            chunk_size = 1000
            for i in range(0, len(objects_to_delete), chunk_size):
                chunk = objects_to_delete[i:i + chunk_size]

                delete_request = {'Objects': chunk}

                minio_storage.s3_client.delete_objects(
                    Bucket=settings.AWS_STORAGE_BUCKET_NAME, Delete=delete_request,
                )
                logger.info(f"{len(chunk)} objects removed")

    logger.info(f"User: '{storage_object.user}' deleted {storage_object.object_type} from DB successful")


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
                f"[{__name__}] User '{user.username}' "
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
