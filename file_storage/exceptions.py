class NameConflictError(Exception):
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

    def get_message(self):
        """
        Формирует сообщение для пользователя на основе деталей конфликта.
        """
        parent_message = f"в папке '{self.parent_name}'" if self.parent_name else "в текущей диретории"

        return f"Файл или папка с таким именем уже существует {parent_message}"