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
    unquoted_path = ''

    if path_param_encoded:
        unquoted_path = urllib.parse.unquote(path_param_encoded)
        path_components = [comp for comp in unquoted_path.split('/') if comp and comp not in ['.', '..']]

        if path_components:
            name_part = path_components[-1]
            path = f"user_{user.id}/{unquoted_path}/"

            if unquoted_path:
                try:
                    current_directory = UserFile.objects.get(
                        user=user,
                        path=path,
                    )

                except UserFile.DoesNotExist:
                    logger.error(
                        f"User '{user.username}': Directory not found for path component '{name_part}' "
                        f"Full requested path: '{unquoted_path}'. Raising Http404."
                    )
                    raise Http404("Запрошенная директория не найдена или не является директорией.")
                except UserFile.MultipleObjectsReturned:
                    logger.error(
                        f"User '{user.username}': Multiple objects returned for path component '{name_part}' "
                        f"Full requested path: '{unquoted_path}'. This indicates a data integrity issue. Raising Http404."
                    )
                    raise Http404("Ошибка при поиске директории (найдено несколько объектов).")

    return current_directory, unquoted_path
