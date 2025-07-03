from django.core.files.uploadedfile import SimpleUploadedFile

from file_storage.tests.base import BaseIntegrationTestCase


class FileUploadIntegrationTest(BaseIntegrationTestCase):
    def test_user_can_upload_file(self):
        user = self.make_user(username="testuser", password="test_password")
        self.login(username="testuser", password="test_password")

        file_content = b"This is a tessssssssssst"
        uploaded_file = SimpleUploadedFile("test_file.txt", file_content, content_type="text/plain")

        upload_url = self.reverse("file_storage:upload_file_ajax")

        response = self.post(
            upload_url,
            data={"files": uploaded_file},
            expected_status_code=200,
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        expected_json = {
            "message": "Все файлы успешно загружены.",
            "results": [
                {
                    "name": "test_file.txt",
                    "status": "success"
                }
            ]
        }
        self.assertJSONEqual(response.content, expected_json)
