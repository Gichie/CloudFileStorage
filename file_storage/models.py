import uuid

from django.contrib.auth import get_user_model
from django.db import models
from storages.backends.s3boto3 import S3Boto3Storage

User = get_user_model()


def user_directory_path(instance, filename):
    return f"user_{instance.user.id}/{filename}"


class UserFile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='files')
    file = models.FileField(upload_to=user_directory_path, storage=S3Boto3Storage())
    original_filename = models.CharField(max_length=255, blank=True)
    file_size = models.PositiveBigIntegerField(null=True, blank=True)
    content_type = models.CharField(max_length=100, null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    last_modified = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.original_filename} (User: {self.user.username})"

    def save(self, *args, **kwargs):
        if not self.pk and self.file:
            self.original_filename = self.file.name.split('/')[-1]
            self.file_size = self.file.size
            self.content_type = self.file.content_type

        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        try:
            self.file.delete(save=False)
        except Exception as e:
            # todo logging
            print(f"Error deleting file {self.file.name} from storage: {e}")
        super().delete(*args, **kwargs)
