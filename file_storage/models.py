import urllib
import uuid

from django.contrib.auth import get_user_model
from django.db import models

User = get_user_model()


def user_directory_path(instance, filename):
    return instance.get_full_path()


class FileType(models.TextChoices):
    FILE = 'file', 'Файл'
    DIRECTORY = 'directory', 'Папка'


class UserFile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='files')
    file = models.FileField(upload_to=user_directory_path, null=True, blank=True, max_length=500)
    path = models.CharField(unique=True, max_length=500, null=True, blank=True)
    name = models.CharField(max_length=255)
    parent = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.CASCADE, related_name='children', db_index=True
    )
    object_type = models.CharField(max_length=10, choices=FileType.choices, default=FileType.FILE)
    file_size = models.PositiveBigIntegerField(null=True, blank=True)
    content_type = models.CharField(max_length=100, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_modified = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'name', 'parent')

    def __str__(self):
        if self.parent:
            return f"{self.name}"
        return str(self.name or "Без названия")

    def is_directory(self):
        return self.object_type == FileType.DIRECTORY

    def get_full_path(self):
        if self.parent:
            parent_path = self.parent.get_full_path()
            return f"{parent_path}{self.name}{'/' if self.is_directory() else ''}"
        else:
            return f"user_{self.user.id}/{self.name}{'/' if self.is_directory() else ''}"

    @property
    def get_display_path(self):
        path = '/'.join(self.path.split('/')[1:])
        return path

    def save(self, *args, **kwargs):
        old_path = self.path if self.pk else None
        self.path = self.get_full_path()

        if self.file and not self.is_directory():
            self.file_size = self.file.size
            self.content_type = self.file.file.content_type

        super().save(*args, **kwargs)

        if old_path and old_path != self.path:
            self.update_children_paths()

    def update_children_paths(self):
        for child in self.children.all():
            child.save()

    def get_s3_key_for_directory_marker(self):
        # Возвращает ключ для объекта-маркера папки в S3 (если используется)
        if self.is_directory():
            # Используем get_full_path() для логического пути папки
            return f"{self.get_full_path()}.empty_folder_marker"
        return None

    def get_path_for_url(self):
        if not self.is_directory():
            return ""
        if self.path:
            return urllib.parse.quote_plus(self.get_display_path[:-1])
