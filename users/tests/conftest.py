from urllib.parse import urlparse

import pytest
from django.conf import settings
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope='session') # Запускаем контейнер один раз на всю сессию тестов
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
    conn_url = postgres_container.get_connection_url()
    parsed_url = urlparse(conn_url)

    bd_name = parsed_url.path.lstrip('/')

    settings.DATABASES['default'].update({
        "ENGINE": "django.db.backends.postgresql",
        "NAME": bd_name,
        "USER": parsed_url.username,
        "PASSWORD": parsed_url.password,
        "HOST": parsed_url.hostname,
        "PORT": parsed_url.port,
        'OPTIONS': {},
        'TEST': {
            'NAME': bd_name
        }
    })

