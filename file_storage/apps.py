from django.apps import AppConfig


class FileStorageConfig(AppConfig):
    """
    Конфигурация приложения `file_storage`.

    Этот класс содержит метаданные и настройки для приложения. Он используется
    Django для интеграции приложения в проект, установки специфичных для него
    параметров и выполнения инициализационных процедур.
    """

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'file_storage'

    def ready(self) -> None:
        """
        Выполняет инициализацию при готовности приложения.

        Этот метод вызывается Django после того, как реестр приложений
        полностью загружен.
        """
        import file_storage.signals  # noqa: F401
