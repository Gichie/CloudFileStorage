from urllib.parse import urlparse

import boto3
import pytest
from django.conf import settings
from django.contrib.auth.models import User
from testcontainers.minio import MinioContainer
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer


@pytest.fixture(scope='session')
def postgres_container():
    """Запускает контейнер с PostgreSQL для всей тестовой сессии."""
    with PostgresContainer("postgres:17-alpine") as postgres:
        yield postgres


@pytest.fixture(scope="session")
def minio_container():
    """Запускает контейнер с MinIO для всей тестовой сессии."""
    with MinioContainer("minio/minio:latest") as minio:
        yield minio


@pytest.fixture(scope="session")
def redis_container():
    """Запускает контейнер с Redis для всей тестовой сессии."""
    with RedisContainer("redis:8.0") as redis:
        yield redis


@pytest.fixture(scope="session", autouse=True)
def override_settings(postgres_container, minio_container, redis_container):
    """
    Переопределяет настройки Django для использования сервисов из testcontainers.
    Эта фикстура выполняется один раз за сессию благодаря scope="session" и autouse=True.
    """
    # Настройка БД
    db_url = postgres_container.get_connection_url()
    parsed_url = urlparse(db_url)

    settings.DATABASES['default'] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed_url.path.lstrip('/'),
        "USER": parsed_url.username,
        "PASSWORD": parsed_url.password,
        "HOST": parsed_url.hostname,
        "PORT": parsed_url.port,
        'ATOMIC_REQUESTS': False,
        'CONN_MAX_AGE': 0,
    }

    # Настройка Minio/S3
    minio_config = minio_container.get_config()
    minio_url = minio_config["endpoint"]
    minio_url = minio_url if minio_url.startswith(("http://", "https://")) else f"http://{minio_url}"
    settings.AWS_S3_ENDPOINT_URL = minio_url
    settings.AWS_ACCESS_KEY_ID = minio_config["access_key"]
    settings.AWS_SECRET_ACCESS_KEY = minio_config["secret_key"]
    settings.AWS_STORAGE_BUCKET_NAME = "test-bucket"

    # Настройка Redis
    redis_host = redis_container.get_container_host_ip()
    redis_port = redis_container.get_exposed_port(6379)
    settings.REDIS_HOST = redis_host
    settings.REDIS_PORT = str(redis_port)


@pytest.fixture(scope="function")
def s3_client():
    """
    Создает и очищает S3 бакет для каждого теста.
    Зависит от настроек, установленных в override_settings.
    """
    client = boto3.client(
        's3',
        endpoint_url=settings.AWS_S3_ENDPOINT_URL,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME,
    )

    bucket_name = settings.AWS_STORAGE_BUCKET_NAME

    try:
        client.create_bucket(Bucket=bucket_name)
    except client.exceptions.BucketAlreadyOwnedByYou:
        pass

    yield client

    bucket_info = client.list_objects_v2(Bucket=bucket_name)
    if "Contents" in bucket_info:
        objects_to_delete = [{"Key": obj["Key"]} for obj in bucket_info["Contents"]]
        client.delete_objects(Bucket=bucket_name, Delete={"Objects": objects_to_delete})
    client.delete_bucket(Bucket=bucket_name)


@pytest.fixture
def test_user():
    """Создает и возвращает тестового пользователя."""
    return User.objects.create_user(username='testuser', password='testpassword')

