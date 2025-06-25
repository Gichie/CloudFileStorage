"""Набор утилит для генерации элементов пользовательского интерфейса."""
import urllib
from typing import Optional

from django.urls import reverse


def generate_breadcrumbs(path_unencoded: str) -> list[dict[str, str]]:
    """
    Генерирует список словарей для "хлебных крошек" на основе пути.

    Каждый словарь содержит 'name' (имя компонента пути) и
    'url_path_encoded' (URL-кодированный путь до этого компонента).

    :param path_unencoded: Строка пути, не кодированная для URL.
    :return: Список словарей для построения "хлебных крошек".
    """
    breadcrumbs: list[dict[str, str]] = []

    if path_unencoded:
        path_parts = path_unencoded.strip('/').split('/')

        for i in range(len(path_parts)):
            unencoded_path = '/'.join(path_parts[:i + 1])
            breadcrumbs.append({
                'name': path_parts[i],
                'url_path_encoded': urllib.parse.quote_plus(unencoded_path)
            })

    return breadcrumbs


def get_parent_url(full_path: str, view_name: str) -> Optional[str]:
    """
    Формирует URL для кнопки "Назад"

    :param full_path: Текущий полный путь (не кодированный).
    :param view_name: Имя URL-шаблона для генерации ссылки.
    :return: Строка URL для родительского уровня или URL для корневого уровня,
             если текущий путь уже корневой или не имеет родителя.
             Возвращает ``None``, если `full_path` пуст и некуда идти "назад".
    """
    if full_path:
        parent_path = '/'.join(full_path.strip('/').split('/')[:-1])
        parent_path_encoded = urllib.parse.quote_plus(parent_path)
        return f"{reverse(view_name)}?path={parent_path_encoded}"

    return None
