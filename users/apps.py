from django.apps import AppConfig


class UsersConfig(AppConfig):
    """
    Конфигурация приложения 'users'.

    Этот класс используется Django для настройки приложения.
    Он устанавливает тип поля для первичного ключа по умолчанию и
    обеспечивает подключение сигналов при готовности приложения.
    """

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'users'

    def ready(self):
        """
        Метод, вызываемый Django, когда приложение готово.

        Импортирует модуль signals, чтобы зарегистрировать обработчики
        сигналов, определенные в этом файле.
        """
        import users.signals  # noqa: F401
