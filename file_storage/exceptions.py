class DatabaseError(Exception):
    """Возникает при ошибках взаимодействия с базой данных."""

    pass


class NameConflictError(DatabaseError):
    """Исключение, возникающее при конфликте имен файлов или папок."""

    def __init__(self, message, name, parent_name=None):
        """
        Инициализация исключения.

        :param message: Общее сообщение об ошибке (для логов).
        :param name: Имя объекта, вызвавшего конфликт.
        :param parent_name: Имя родительской директории (для более понятного сообщения).
        """
        super().__init__(message)
        self.name = name
        self.parent_name = parent_name


class StorageError(Exception):
    """Возникает при ошибках взаимодействия с файловым хранилищем (S3/Minio)."""

    pass


class InvalidPathError(Exception):
    """Возникает при попытке использовать некорректный или небезопасный путь."""

    pass
