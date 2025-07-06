from botocore.exceptions import ClientError
from django.conf import settings
from django.urls import reverse

from file_storage.models import UserFile, FileType
from file_storage.tests.base import BaseIntegrationTestCase


class TestCreateDirectory(BaseIntegrationTestCase):
    def test_create_valid_directory(self, client, s3_client, test_user):
        """Создание валидной папки."""
        client.force_login(test_user)
        dir_name = "test_directory"
        create_directory_url = reverse("file_storage:list_files")
        
        response = client.post(
            create_directory_url,
            data={"name": dir_name},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        assert response.status_code == 201
        assert UserFile.objects.count() == 1
        assert UserFile.objects.filter(
            name=dir_name, object_type=FileType.DIRECTORY, user=test_user
        ).exists()
        directory = UserFile.objects.get(
                name=dir_name, object_type=FileType.DIRECTORY, user=test_user
            )
        key = f"{directory.path}.empty_folder_marker"
        try:
            s3_client.head_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=key)
            marker_exists_in_s3 = True
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                marker_exists_in_s3 = False
            else:
                raise

        assert marker_exists_in_s3, f"Маркерный файл '{key}' не найден в S3/MinIO."
