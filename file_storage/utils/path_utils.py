import logging
import urllib

from django.urls import reverse

logger = logging.getLogger(__name__)


def encode_path_for_url(unencoded_path: str, view_name: str) -> str:
    """
    Кодирует путь для использования в URL и генерирует полный URL к указанному view.

    Использует `urllib.parse.quote_plus` для кодирования пути,
    что заменяет пробелы на '+' и кодирует другие специальные символы.

    :param unencoded_path: Строка с путем, который нужно закодировать.
    :param view_name: Имя URL-шаблона Django.
    :return: Строка с полным URL, включающим закодированный путь как query-параметр 'path'.
    """
    encoded_path: str = urllib.parse.quote_plus(unencoded_path)
    return f"{reverse(view_name)}?path={encoded_path}"
