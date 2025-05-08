import io

import boto3

from cloud_file_storage import settings


def get_s3_client():
    return boto3.client(
        's3',
        endpoint_url=settings.AWS_S3_ENDPOINT_URL,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME,
    )


def create_empty_directory_marker(s3_client, bucket: str, key: str):
    """
    Создаёт пустой объект в MinIO для обозначения директории.
    """
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=io.BytesIO(b'')
    )
