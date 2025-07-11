import io

import pytest
from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from file_storage.models import UserFile
from file_storage.tests.base import BaseIntegrationTestCase


class TestFileUploadIntegration(BaseIntegrationTestCase):
    def test_user_can_upload_file(self, client, s3_client, test_user):
        """
        Проверяет, что авторизованный пользователь может загрузить файл.

        Система должна вернуть статус успеха и изменить состояние БД и S3.
        """
        client.force_login(test_user)

        file_content = b"This is a test"
        file_name = "test_file.txt"
        uploaded_file = SimpleUploadedFile(file_name, file_content, content_type="text/plain")
        upload_url = reverse("file_storage:upload_file_ajax")

        response = client.post(
            upload_url,
            data={"files": uploaded_file},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        assert response.status_code == 200

        response_data = response.json()

        expected_json = {
            "message": "Все файлы успешно загружены.",
            "results": [{"name": "test_file.txt", "status": "success"}],
        }

        assert response_data == expected_json

        assert UserFile.objects.count() == 1
        db_file = UserFile.objects.first()
        assert db_file.user == test_user
        assert db_file.name == file_name

        try:
            s3_object = s3_client.get_object(
                Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                Key=db_file.path
            )
        except s3_client.exceptions.ClientError as err:
            pytest.fail(f"Файл не найден в MinIO по ключу {db_file.path}. Ошибка: {err}")
        else:
            assert s3_object["ContentType"] == "text/plain"
            s3_object_content = s3_object["Body"].read()
            assert s3_object_content == file_content

    def test_unauthorized_user_uploaded_file(self, client, s3_client):
        """
        Проверяет, что неавторизованный пользователь не может загрузить файл.

        Система должна вернуть статус редиректа и не изменять состояние БД и S3.
        """
        file_content = b"This is a test"
        file_name = "test_file.txt"
        uploaded_file = SimpleUploadedFile(file_name, file_content, content_type="text/plain")
        upload_url = reverse("file_storage:upload_file_ajax")

        response = client.post(
            upload_url,
            data={"files": uploaded_file},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        assert response.status_code == 302
        assert UserFile.objects.count() == 0

        s3_response = s3_client.list_objects_v2(Bucket=settings.AWS_STORAGE_BUCKET_NAME)
        assert "Contents" not in s3_response

    def test_file_with_exists_name(self, client, s3_client, test_user):
        """Загрузка уже такого же существующего файла."""
        client.force_login(test_user)

        file_content = b"This is a test"
        file_name = "test_file.txt"
        uploaded_file = SimpleUploadedFile(file_name, file_content, content_type="text/plain")
        upload_url = reverse("file_storage:upload_file_ajax")

        for _ in range(2):
            response = client.post(
                upload_url,
                data={"files": uploaded_file},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )

        assert response.status_code == 400
        assert UserFile.objects.count() == 1

    def test_file_with_uncorrected_name(self, client, test_user):
        """Попытка загрузить файл с пустым именем прерывается исключением SuspiciousFileOperation."""
        client.force_login(test_user)

        file_content = b"This is a test"

        for file_name in ("", ".", "..", "/"):
            with pytest.raises(SuspiciousFileOperation):
                SimpleUploadedFile(file_name, file_content, content_type="text/plain")

    def test_uncorrected_size(self, client, s3_client, test_user):
        """Попытка загрузить файл с некорректным размером файла: больше чем лимит."""
        client.force_login(test_user)

        limit_size = settings.DATA_UPLOAD_MAX_MEMORY_SIZE + 1

        file_name = "large_file.ogo"

        upload_url = reverse("file_storage:upload_file_ajax")

        large_content = io.BytesIO(b'\0' * limit_size)

        uploaded_file = SimpleUploadedFile(
            name=file_name,
            content=large_content.read(),  # Читаем содержимое из BytesIO
            content_type="application/octet-stream"
        )

        response = client.post(
            upload_url,
            data={"files": uploaded_file},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        assert response.status_code == 400
        assert UserFile.objects.count() == 0

        s3_response = s3_client.list_objects_v2(Bucket=settings.AWS_STORAGE_BUCKET_NAME)
        assert "Contents" not in s3_response

    def test_multiple_file_uploads_successful(self, client, s3_client, test_user):
        """Попытка загрузить несколько валидных файлов."""
        client.force_login(test_user)
        num_files = 3
        upload_url = reverse("file_storage:upload_file_ajax")
        file_content = b"This is a test"
        uploaded_files = []

        for i in range(num_files):
            file_name = f"test_file_{i}.txt"
            uploaded_file = SimpleUploadedFile(file_name, file_content, content_type="text/plain")
            uploaded_files.append(uploaded_file)
            upload_url = reverse("file_storage:upload_file_ajax")

        response = client.post(
            upload_url,
            data={"files": uploaded_files},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        assert response.status_code == 200
        assert UserFile.objects.count() == num_files
        s3_response = s3_client.list_objects_v2(Bucket=settings.AWS_STORAGE_BUCKET_NAME)
        assert len(s3_response["Contents"]) == num_files

    def test_multiple_file_uploads_partially_successful(self, client, s3_client, test_user):
        """Попытка загрузить несколько файлов фалидных и нет."""
        client.force_login(test_user)
        num_files = 3
        upload_url = reverse("file_storage:upload_file_ajax")
        file_content = b"This is a test"
        uploaded_files = []

        for i in range(num_files):
            file_name = f"test_file_{i % 2}.txt"
            uploaded_file = SimpleUploadedFile(file_name, file_content, content_type="text/plain")
            uploaded_files.append(uploaded_file)
            upload_url = reverse("file_storage:upload_file_ajax")

        response = client.post(
            upload_url,
            data={"files": uploaded_files},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        assert response.status_code == 207
        assert UserFile.objects.count() == num_files - 1

        s3_response = s3_client.list_objects_v2(Bucket=settings.AWS_STORAGE_BUCKET_NAME)
        assert len(s3_response["Contents"]) == num_files - 1
