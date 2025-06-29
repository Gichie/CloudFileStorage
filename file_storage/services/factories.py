from django.contrib.auth.models import User

from file_storage.services.directory_service import DirectoryService
from file_storage.services.upload_service import UploadService
from file_storage.storages.minio import minio_client


def create_upload_service(user: User) -> UploadService:
    """Собирает и возвращает экземпляр UploadService со всеми зависимостями.

    Эта фабричная функция инкапсулирует логику создания сервиса `UploadService`.

    :param user: Объект пользователя, для которого будет выполняться
                 операция загрузки. Передается во все дочерние сервисы.
    :return: Полностью сконфигурированный и готовый к использованию
             экземпляр `UploadService`.
    """
    directory_service = DirectoryService(user, minio_client)
    upload_service = UploadService(user, directory_service)

    return upload_service
