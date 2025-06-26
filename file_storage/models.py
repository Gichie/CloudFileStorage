import datetime
import urllib
import uuid
from typing import Optional, TYPE_CHECKING

from django.conf import settings
from django.db import models
from django.db.models import QuerySet

if TYPE_CHECKING:
    from django.contrib.auth.models import User


def user_directory_path(instance, filename):
    return instance.get_full_path()


class FileType(models.TextChoices):
    """Перечисление типов объектов в файловом хранилище."""
    FILE: str = 'file', 'Файл'
    DIRECTORY: str = 'directory', 'Папка'


class UserFileManager(models.Manager):
    """
    Менеджер для модели UserFile, предоставляющий кастомные методы для работы с файлами и папками.
    """

    def get_all_children_files(self, directory: 'UserFile'):
        """
        Получает все дочерние объекты (файлы и папки) внутри указанной директории.

        Выполняет рекурсивный поиск по пути. Если переданный объект не является
        директорией, возвращает пустой QuerySet.

        :param directory: Объект UserFile, представляющий директорию, для которой
                          необходимо получить дочерние элементы.
        :returns: QuerySet, содержащий все дочерние UserFile объекты,
                  отсортированные по пути и имени, или пустой QuerySet.
        """
        if directory.object_type == FileType.DIRECTORY:
            all_files = (self.filter(
                user=directory.user, path__startswith=directory.path
            ).select_related('user').only(
                'id', 'name', 'path', 'object_type', 'file', 'user__id'
            ).order_by('path', 'name'))
        else:
            return self.none()

        return all_files

    def available_directories_to_move(self, user: 'User', item_id: str) -> QuerySet['UserFile']:
        """
        Возвращает QuerySet с директориями, доступными для перемещения.

        Логика исключений:
        1. Нельзя переместить объект в его текущую родительскую директорию.
        2. Если перемещается директория, нельзя переместить ее в саму себя
           или в любую из ее дочерних директорий.

        :param user: Пользователь, владелец объектов.
        :param item_id: ID объекта (папки или файла), который нужно переместить.
        :return: QuerySet объектов UserFile, представляющих доступные директории.
        """
        item = self.get(user=user, id=item_id)
        res = self.filter(user=user, object_type=FileType.DIRECTORY).exclude(id=item.parent_id)

        if item.object_type == FileType.DIRECTORY:
            res = res.exclude(path__startswith=item.path)

        return res

    def object_with_name_exists(self, user: 'User', object_name: str,
                                parent_object: Optional['UserFile'] = None) -> bool:
        """Проверяет существование объекта (файла или папки) с указанным именем
        в заданной родительской директории для конкретного пользователя.

        :param user: Пользователь, владелец объекта.
        :param object_name: Имя проверяемого объекта.
        :param parent_object: Родительская директория. Если ``None``, проверяется
                              существование в корневой директории пользователя.
        :return: ``True``, если объект с таким именем уже существует, иначе ``False``.
        """
        return self.filter(
            user=user,
            name=object_name,
            parent=parent_object,
        ).exists()

    def file_exists(self, user: 'User', parent: Optional['UserFile'], name: str) -> bool:
        """
        Проверяет существование файла или папки с указанным именем в родительской директории
        для конкретного пользователя.

        :param user: Пользователь, владелец объекта.
        :param parent: Родительская папка. None для корневой директории.
        :param name: Имя файла или папки для проверки.
        :return: True, если объект существует, иначе False.
        """
        return self.filter(
            user=user,
            parent=parent,
            name=name,
        ).exists()


class UserFile(models.Model):
    """Модель, представляющая файл или директорию пользователя."""
    id: uuid.UUID = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='files')
    file = models.FileField(upload_to=user_directory_path, null=True, blank=True, max_length=500)
    path: str = models.CharField(unique=True, max_length=500, null=True, blank=True)
    name: str = models.CharField(max_length=255)
    parent: Optional['UserFile'] = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.CASCADE, related_name='children', db_index=True
    )
    object_type: str = models.CharField(max_length=10, choices=FileType.choices, default=FileType.FILE)
    file_size: int | None = models.PositiveBigIntegerField(null=True, blank=True)
    content_type: str | None = models.CharField(max_length=100, null=True, blank=True)
    created_at: datetime = models.DateTimeField(auto_now_add=True)
    last_modified: datetime = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'name', 'parent')

    objects: UserFileManager = UserFileManager()

    def __str__(self):
        if self.parent:
            return f"{self.name}"
        return str(self.name or "Без названия")

    def is_directory(self) -> bool:
        """Проверяет, является ли данный объект директорией.

        :return: ``True``, если объект является директорией, иначе ``False``.
        """
        return self.object_type == FileType.DIRECTORY

    def get_full_path(self) -> str:
        """Формирует и возвращает полный логический путь к объекту.

        Путь строится рекурсивно на основе родительских директорий.
        Для корневых объектов путь начинается с "user_{user_id}/".
        Для директорий путь заканчивается слешем. Файлы не имеют слеша на конце.

        :return: Строка, представляющая полный логический путь к объекту.
        """
        if self.parent:
            parent_path = self.parent.get_full_path()
            return f"{parent_path}{self.name}{'/' if self.is_directory() else ''}"
        else:
            return f"user_{self.user.id}/{self.name}{'/' if self.is_directory() else ''}"

    @property
    def get_display_path(self) -> str:
        """
        Возвращает "чистый" путь к объекту для отображения пользователю.

        Предполагается, что полный путь имеет вид 'user/folder/file',
        где 'user' - это служебный префикс, который не нужно показывать.
        Этот метод отсекает первую часть пути.
        """
        path = '/'.join(self.path.split('/')[1:])
        return path

    def save(self, *args, **kwargs) -> None:
        """Переопределенный метод сохранения модели.

        Устанавливает полный путь (`path`) объекта перед сохранением.
        Если объект является файлом и имеет связанный файл (`self.file`),
        обновляет `file_size` и `content_type`.

        :param args: Позиционные аргументы для родительского метода `save`.
        :param kwargs: Именованные аргументы для родительского метода `save`.
        """
        self.path = self.get_full_path()

        if self.file and not self.is_directory():
            if not self.file_size:
                self.file_size = self.file.size
            self.file.name = self.path
            if not self.content_type:
                self.content_type = self.file.file.content_type

        super().save(*args, **kwargs)

    def get_s3_key_for_directory_marker(self) -> str | None:
        """Возвращает ключ S3 для объекта-маркера, если текущий объект - директория.

        Маркер используется для представления пустых директорий в S3-совместимых хранилищах.
        Имя маркера формируется добавлением суффикса ".empty_folder_marker" к полному пути директории.
        Полный путь директории должен уже заканчиваться на '/'.

        :return: Строку с ключом S3 для маркера директории, или ``None``,
        если объект не является директорией.
        """
        if self.is_directory():
            # Используем get_full_path() для логического пути папки
            return f"{self.get_full_path()}.empty_folder_marker"
        return None

    def get_path_for_url(self):
        if not self.is_directory():
            return ""
        if self.path:
            return urllib.parse.quote_plus(self.get_display_path[:-1])
