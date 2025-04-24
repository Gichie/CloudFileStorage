from urllib.parse import urlparse

import pytest
from django.conf import settings
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope='session')
def postgres_container():
    # Используем образ PostgreSQL
    container = PostgresContainer("postgres:17-alpine")
    try:
        container.start()
        yield container
    finally:
        container.stop()


@pytest.fixture(scope='session', autouse=True)
def override_db_settings(postgres_container):
    """
    Переопределяет настройки базы данных Django для использования
    базы данных из запущенного Testcontainer.
    """
    # Получаем URL подключения из контейнера
    conn_url = postgres_container.get_connection_url()

    # Разбираем URL для получения компонентов
    parsed_url = urlparse(conn_url)

    # Получаем имя базы данных из пути URL
    db_name = parsed_url.path.lstrip('/')

    # Берем параметры напрямую из URL
    username = parsed_url.username
    password = parsed_url.password
    host = parsed_url.hostname
    port = parsed_url.port

    print(f"DB settings: {db_name}, {username}, {password}, {host}, {port}")

    # Обновляем настройки Django
    settings.DATABASES['default'] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": db_name,
        "USER": username,
        "PASSWORD": password,
        "HOST": host,
        "PORT": port,
        'OPTIONS': {},
        'ATOMIC_REQUESTS': False,  # Добавляем этот параметр
        'CONN_MAX_AGE': 0,
    }
