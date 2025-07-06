import boto3
import pytest
from django.conf import settings
from django.contrib.auth.models import User
from testcontainers.minio import MinioContainer
from testcontainers.redis import RedisContainer


@pytest.fixture(scope="session")
def minio_container():
    with MinioContainer("minio/minio:latest") as minio:
        yield minio


@pytest.fixture(scope="session")
def redis_container():
    with RedisContainer("redis:8.0") as redis:
        yield redis


@pytest.fixture(autouse=True)
def django_settings(minio_container, redis_container):
    minio_config = minio_container.get_config()
    minio_url = minio_config["endpoint"]
    minio_url = minio_url if minio_url.startswith(("http://", "https://")) else f"http://{minio_url}"
    minio_access_key = minio_config["access_key"]
    minio_secret_key = minio_config["secret_key"]

    redis_host = redis_container.get_container_host_ip()
    redis_port = redis_container.get_exposed_port(6379)

    settings.AWS_S3_ENDPOINT_URL = minio_url
    settings.AWS_ACCESS_KEY_ID = minio_access_key
    settings.AWS_SECRET_ACCESS_KEY = minio_secret_key
    settings.AWS_STORAGE_BUCKET_NAME = "test-bucket"
    settings.REDIS_HOST = redis_host
    settings.REDIS_PORT = str(redis_port)


@pytest.fixture
def s3_client(django_settings):
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
