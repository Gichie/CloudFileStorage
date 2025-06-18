import logging

from file_storage.exceptions import NameConflictError, StorageError
from file_storage.services.directory_service import DirectoryService
from file_storage.services.file_service import FileService


logger = logging.getLogger(__name__)


def handle_file_upload(uploaded_file, user, parent_object, relative_path, cache):
    """
    Обрабатывает один загруженный файл: проверяет, создает UserFile, загружает файл в Minio через FileField.
    Возвращает словарь с результатом.
    """
    uploaded_file_name = uploaded_file.name
    dir_path = None
    log_prefix = (f"User '{user.username}' (ID: {user.id}), File '{uploaded_file_name}', "
                  f"Parent ID: {parent_object.id if parent_object else 'None'}, relative_path: {relative_path}")

    if relative_path:
        path_components = [component for component in relative_path.split('/') if component]
        dir_path = '/'.join(path_components[:-1])

        if not path_components:
            logger.warning(f"Invalid relative path {log_prefix}")
            return {
                'name': uploaded_file_name,
                'status': 'error',
                'error': f'Некорректный относительный путь {relative_path}'
            }

        directory_path_parts = path_components[:-1]

        if dir_path not in cache:
            try:
                parent_object = DirectoryService.get_parent_or_create_directories_from_path(
                    user, parent_object, directory_path_parts
                )

            except NameConflictError as e:
                return {
                    'name': e.name,
                    'status': 'error',
                    'error': e.get_message(),
                    'relative_path': relative_path
                }
            except StorageError:
                # Логирвание ниже в create_directories_from_path
                return {
                    'name': uploaded_file_name,
                    'status': 'error',
                    'error': f'Ошибка при создании структуры папок',
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
        else:
            parent_object = cache[dir_path]

    return FileService.create_file(user, uploaded_file, parent_object, log_prefix), dir_path, parent_object


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
