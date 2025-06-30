from storages.backends.s3boto3 import S3Boto3Storage


class CustomS3Boto3Storage(S3Boto3Storage):
    """Кастомное хранилище на базе S3Boto3Storage, переопределяющее метод очистки имени файла."""

    def get_valid_name(self, name: str) -> str:
        """
        Возвращает имя файла без какой-либо обработки или очистки.

        Переопределяет стандартное поведение, которое удаляет небезопасные
        символы и заменяет пробелы.

        :param name: Исходное имя файла, предложенное для сохранения.
        :return: То же самое имя, без изменений.
        """
        return name
