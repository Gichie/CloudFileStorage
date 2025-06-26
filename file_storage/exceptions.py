class DatabaseError(Exception):
    pass


class NameConflictError(DatabaseError):
    """
    Исключение, возникающее при конфликте имен файлов или папок.
    """

    def __init__(self, message, name, parent_name=None):
        """
        :param message: Общее сообщение об ошибке (для логов).
        :param name: Имя объекта, вызвавшего конфликт.
        :param parent_name: Имя родительской директории (для более понятного сообщения).
        """
        super().__init__(message)
        self.name = name
        self.parent_name = parent_name


class StorageError(Exception):
    pass


class InvalidPathError(Exception):
    pass
