import urllib

from django.urls import reverse


def generate_breadcrumbs(path_unencoded):
    """
    Генерирует breadcrumbs для навигации
    """
    breadcrumbs = []

    if path_unencoded:
        path_parts = path_unencoded.strip('/').split('/')

        for i in range(len(path_parts)):
            unencoded_path = '/'.join(path_parts[:i+1])
            breadcrumbs.append({
                'name': path_parts[i],
                'url_path_encoded': urllib.parse.quote_plus(unencoded_path)
            })

    return breadcrumbs


def get_parent_url(full_path, view_name):
    """
    Формирует URL для кнопки "Назад"
    """
    if full_path:
        parent_path = '/'.join(full_path.strip('/').split('/')[:-1])
        parent_path_encoded = urllib.parse.quote_plus(parent_path)
        return f"{reverse(view_name)}?path={parent_path_encoded}"

    return None
