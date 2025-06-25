import logging

from django.core.exceptions import SuspiciousFileOperation

from file_storage.exceptions import NameConflictError, InvalidPathError
from file_storage.models import UserFile, FileType

logger = logging.getLogger(__name__)


class FileService:
    @staticmethod
    def create_file(user, uploaded_file, parent_object, log_prefix=None):
        if UserFile.objects.file_exists(user, parent_object, uploaded_file.name):
            message = f"Upload failed. File or directory with this name already exists. {log_prefix}"
            logger.error(message, exc_info=True)
            raise NameConflictError('Такой файл уже существует', uploaded_file.name, parent_object.name)

        try:
            user_file_instance = UserFile(
                user=user,
                file=uploaded_file,
                name=uploaded_file.name,
                parent=parent_object,
                object_type=FileType.FILE,
            )
            user_file_instance.save()

            logger.debug(
                f"{user_file_instance.object_type} successfully uploaded and saved. {log_prefix}. "
                f"UserFile ID: {user_file_instance.id}, Minio Path: {user_file_instance.file.name}"
            )

        except SuspiciousFileOperation as e:
            logger.warning(f"Loading error: path too long {log_prefix}: {e}", exc_info=True)
            raise InvalidPathError()
