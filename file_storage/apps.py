from django.apps import AppConfig


class FileStorageConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'file_storage'

    def ready(self):
        import file_storage.signals
