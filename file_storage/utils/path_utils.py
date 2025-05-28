import logging
import urllib

from django.http import Http404

from file_storage.models import UserFile, FileType

logger = logging.getLogger(__name__)


def parse_directory_path(user, path_param_encoded):
    """
    Парсит закодированный путь и возвращает объект директории и декодированный путь
    """
    current_directory = None
    current_path_unencoded = ''

    if path_param_encoded:
        unquoted_path = urllib.parse.unquote(path_param_encoded)
        path_components = [comp for comp in unquoted_path.split('/') if comp and comp not in ['.', '..']]
        current_path_unencoded = "/".join(path_components)
        current_parent_obj = None

        if current_path_unencoded:
            try:
                for name_part in path_components:
                    obj = UserFile.objects.get(
                        user=user,
                        name=name_part,
                        parent=current_parent_obj,
                        object_type=FileType.DIRECTORY
                    )
                    current_parent_obj = obj
                current_directory = current_parent_obj

            except UserFile.DoesNotExist:
                logger.error(
                    f"User '{user.username}': Directory not found for path component '{name_part}' "
                    f"Full requested path: '{current_path_unencoded}'. Raising Http404."
                )
                raise Http404("Запрошенная директория не найдена или не является директорией.")
            except UserFile.MultipleObjectsReturned:
                logger.error(
                    f"User '{user.username}': Multiple objects returned for path component '{name_part}' "
                    f"Full requested path: '{current_path_unencoded}'. This indicates a data integrity issue. Raising Http404."
                )
                raise Http404("Ошибка при поиске директории (найдено несколько объектов).")

    return current_directory, current_path_unencoded
