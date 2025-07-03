import boto3
import pytest

from testcontainers.minio import MinioContainer
from testcontainers.redis import RedisContainer

from cloud_file_storage import settings


@pytest.fixture(scope="session")
def minio_container():
    with MinioContainer("minio/minio:latest") as minio:
        yield minio


@pytest.fixture(scope="session")
def redis_container():
    with RedisContainer("redis:8.0") as redis:
        yield redis


@pytest.fixture
def django_settings(settings, minio_container, redis_container):
    minio_config = minio_container.get_config()
    minio_url = minio_config["endpoint"]
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
        "s3",
        endpoint_url=settings.AWS_S3_ENDPOINT_URL,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=getattr(settings, "AWS_S3_REGION_NAME", None),
    )

    bucket_name = settings.AWS_STORAGE_BUCKET_NAME
    print(bucket_name)

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


@pytest.fixture(autouse=True)
def setup_s3_client_on_self(request, s3_client):
    """Эта фикстура автоматически прикрепляет s3_client к экземпляру тестового класса."""
    if hasattr(request, "instance") and request.instance:
        from file_storage.tests.base import BaseIntegrationTestCase
        if isinstance(request.instance, BaseIntegrationTestCase):
            request.s3_client = s3_client
