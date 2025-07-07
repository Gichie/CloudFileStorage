from typing import Any

from django.contrib.auth.models import AnonymousUser
from django.http.request import HttpRequest
from django.utils.functional import cached_property
from django.views.generic.base import ContextMixin

from file_storage.services.directory_service import DirectoryService
from file_storage.services.file_service import FileService
from file_storage.storages.minio import minio_client


class QueryParamMixin(ContextMixin):
    """
    Миксин для добавления закодированных GET-параметров в контекст шаблона.

    Используется для сохранения параметров запроса при переходе по страницам пагинации.
    Исключает параметр 'page' из сохраняемых параметров.
    """

    request: HttpRequest

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """
        Добавляет 'query_params' в контекст.

        'query_params' содержит строку URL-кодированных GET-параметров
        текущего запроса, за исключением параметра 'page'.

        :param kwargs: Дополнительные аргументы контекста.
        :return: Словарь данных контекста с добавленным 'query_params'.
        """
        context = super().get_context_data(**kwargs)

        query_params = self.request.GET.copy()
        query_params.pop('page', None)
        encode_params: str = query_params.urlencode()

        context['query_params'] = encode_params

        return context


class DirectoryServiceMixin:
    """
    Миксин для предоставления экземпляра DirectoryService в Class-Based Views.

    Создает и кэширует экземпляр сервиса для текущего запроса.
    Доступен в view через `self.service`.
    """

    request: HttpRequest

    @cached_property
    def service(self) -> DirectoryService:
        """Возвращает экземпляр DirectoryService, инициализированный для текущего пользователя."""
        return DirectoryService(user=self.request.user, s3_client=minio_client)


class FileServiceMixin:
    """
    Миксин для предоставления экземпляра FileService в Class-Based Views.

    Создает и кэширует экземпляр сервиса для текущего запроса.
    Доступен в view через `self.service`.
    """

    request: HttpRequest

    @cached_property
    def service(self) -> FileService:
        """Возвращает экземпляр FileService, инициализированный для текущего пользователя."""
        assert not isinstance(self.request.user, AnonymousUser), "Authentication required"
        return FileService(user=self.request.user, s3_client=minio_client)


class ErrorFormatingMixin:
    """Миксин для FileUploadForm"""

    def handle_form_validation_error(self) -> str:
        """
        Формирует строку ошибок из невалидной формы.

        :return: Строка, содержащая все сообщения об ошибках.
        """
        if not self.errors:
            return ""
        error_messages: list[str] = []
        for field, errors in self.errors.items():
            error_string = '; '.join(map(str, errors))
            error_messages.append(f"{field}: {error_string}")

        return "\n".join(error_messages)
