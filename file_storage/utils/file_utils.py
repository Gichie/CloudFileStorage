import logging

from django.core.exceptions import SuspiciousFileOperation

from file_storage.models import UserFile, FileType

logger = logging.getLogger(__name__)


def file_exists(user, parent, name):
    """Проверяет существование файла с указанным именем в родительской директории"""
    return UserFile.objects.filter(
        user=user,
        parent=parent,
        name=name,
    ).exists()


def get_all_files(directory, user, type_flag=None):
    """
    Получает все файлы рекурсивно одним запросом
    """

    all_files = (UserFile.objects.filter(
        user=user, path__startswith=directory.path
    ).exclude(
        id=directory.id
    ).select_related('user').only(
        'id', 'name', 'path', 'object_type', 'file', 'user__id'
    ).order_by('path', 'name'))

    return all_files


def create_file(user, uploaded_file, parent_object, log_prefix=None):
    if file_exists(user, parent_object, uploaded_file.name):
        message = f"Upload failed. File or directory with this name already exists. {log_prefix}"
        logger.warning(message)
        return {
            'name': uploaded_file.name,
            'status': 'error',
            'error': 'Такой файл уже существует'
        }

    try:
        user_file_instance = UserFile(
            user=user,
            file=uploaded_file,
            name=uploaded_file.name,
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
            'name': uploaded_file.name,
            'status': 'error',
            'error': 'Ошибка при загрузке файла: слишком длинный путь для файла'
        }
    except Exception as e:
        logger.error(
            f"{log_prefix} Error during file save or Minio upload: {e}",
            exc_info=True
        )
        return {
            'name': uploaded_file.name,
            'status': 'error',
            'error': 'Ошибка при загрузке файла в хранилище'
        }
