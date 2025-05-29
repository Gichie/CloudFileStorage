import logging

from django.core.exceptions import SuspiciousFileOperation
from django.db import transaction

from file_storage.exceptions import NameConflictError
from file_storage.models import UserFile, FileType
from file_storage.utils import directory_utils

logger = logging.getLogger(__name__)


def file_exists(user, parent, name):
    """Проверяет существование файла с указанным именем в родительской директории"""
    return UserFile.objects.filter(
        user=user,
        parent=parent,
        name=name,
    ).exists()


def handle_file_upload(uploaded_file, user, parent_object, relative_path):
    """
    Обрабатывает один загруженный файл: проверяет, создает UserFile, загружает файл в Minio через FileField.
    Возвращает словарь с результатом.
    """

    uploaded_file_name = uploaded_file.name

    log_prefix = (f"User '{user.username}' (ID: {user.id}), File '{uploaded_file_name}', "
                  f"Parent ID: {parent_object.id if parent_object else 'None'}, relative_path: {relative_path}")

    if relative_path:
        path_components = [component for component in relative_path.split('/') if component]

        if not path_components:
            logger.warning(f"Invalid relative path {log_prefix}")
            return {
                'name': uploaded_file_name,
                'status': 'error',
                'error': f'Некорректный относительный путь {relative_path}'
            }

        directory_path_parts = path_components[:-1]

        try:
            if directory_path_parts:
                with transaction.atomic():
                    parent_object = directory_utils.create_directories_from_path(
                        user, parent_object, directory_path_parts
                    )

        except NameConflictError as e:
            return {
                'name': e.name,
                'status': 'error',
                'error': e.get_message(),
                'relative_path': relative_path
            }

        except Exception as e:
            logger.error(
                f"Failed to create directory structure for '{relative_path}'. User: {user.username}. Error: {e}",
                exc_info=True
            )
            return {
                'name': uploaded_file_name,
                'status': 'error',
                'error': f'Ошибка при создании структуры папок',
                'relative_path': relative_path
            }

    if file_exists(user, parent_object, uploaded_file_name):
        message = f"Upload failed. File or directory with this name already exists. {log_prefix}"
        logger.warning(message)
        raise NameConflictError(message, uploaded_file_name, parent_object)

    try:
        with transaction.atomic():
            user_file_instance = UserFile(
                user=user,
                file=uploaded_file,
                name=uploaded_file_name,
                parent=parent_object,
                object_type=FileType.FILE,
            )
            user_file_instance.save()

            logger.info(
                f"{log_prefix} Successfully uploaded and saved. "
                f"UserFile ID: {user_file_instance.id}, Minio Path: {user_file_instance.file.name}"
            )

            return {
                'name': user_file_instance.name,
                'status': 'success',
                'id': str(user_file_instance.id)
            }

    except SuspiciousFileOperation as e:
        logger.warning(f"Loading error: path too long {log_prefix}: {e}", exc_info=True)
        return {
            'name': uploaded_file_name,
            'status': 'error',
            'error': 'Ошибка при загрузке файла: слишком длинный путь для файла'
        }
    except Exception as e:
        logger.error(
            f"{log_prefix} Error during file save or Minio upload: {e}",
            exc_info=True
        )
        return {
            'name': uploaded_file_name,
            'status': 'error',
            'error': 'Ошибка при загрузке файла в хранилище'
        }


def get_message_and_status(results):
    any_errors = any(res['status'] == 'error' for res in results)

    if any_errors:
        if all(res['status'] == 'error' for res in results):
            message = 'Файл не удалось загрузить.'
        else:
            message = 'Некоторые файлы были загружены с ошибкой.'
    else:
        message = 'Все файлы успешно загружены.'

    http_status = 200
    if any_errors:
        http_status = 207

    return {'message': message, 'results': results}, http_status
