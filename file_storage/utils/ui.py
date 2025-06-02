import urllib

from django.urls import reverse


def generate_breadcrumbs(path_unencoded):
    """
    Генерирует breadcrumbs для навигации
    """
    breadcrumbs = []

    if path_unencoded:
        path_parts = path_unencoded.split('/')

        while path_parts:
            temp_dir_name = path_parts[-1]
            breadcrumbs.insert(0, {
                'name': temp_dir_name,
                'url_path_encoded': urllib.parse.quote_plus('/'.join(path_parts))
            })
            path_parts.pop()

    return breadcrumbs


def get_parent_url(full_path, view_name):
    """
    Формирует URL для кнопки "Назад"
    """
    if full_path:
        parent_path = '/'.join(full_path.split('/')[:-1])
        parent_path_encoded = urllib.parse.quote_plus(parent_path)
        return f"{reverse(view_name)}?path={parent_path_encoded}"

    return None
