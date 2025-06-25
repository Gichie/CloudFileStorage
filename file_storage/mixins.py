from typing import Any


class QueryParamMixin:
    """
    Миксин для добавления закодированных GET-параметров в контекст шаблона.

    Используется для сохранения параметров запроса при переходе по страницам пагинации.
    Исключает параметр 'page' из сохраняемых параметров.
    """
    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """
        Добавляет 'query_params' в контекст.

        'query_params' содержит строку URL-кодированных GET-параметров
        текущего запроса, за исключением параметра 'page'.

        :param kwargs: Дополнительные аргументы контекста.
        :return: Словарь данных контекста с добавленным 'query_params'.
        """
        context = super().get_context_data(**kwargs)

        query_params: dict[str, Any] = self.request.GET.copy()
        query_params.pop('page', None)
        encode_params: str = query_params.urlencode()

        context['query_params'] = encode_params

        return context
