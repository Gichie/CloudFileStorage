import urllib

from django.urls import reverse


def generate_breadcrumbs(directory, path_unencoded):
    """
    Генерирует breadcrumbs для навигации
    """
    breadcrumbs = []

    if directory:
        temp_dir = directory
        path_parts = path_unencoded.split('/')

        while temp_dir:
            breadcrumbs.insert(0, {
                'name': temp_dir.name,
                'url_path_encoded': urllib.parse.quote_plus('/'.join(path_parts))
            })
            path_parts.pop()
            temp_dir = temp_dir.parent

    return breadcrumbs


def get_parent_url(directory, view_name):
    """
    Формирует URL для кнопки "Назад"
    """
    if directory and directory.parent:
        parent_path_encoded = directory.parent.get_path_for_url()
        return f"{reverse(view_name)}?path={parent_path_encoded}"
    elif directory:
        return reverse(view_name)
    return None
