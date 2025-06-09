class QueryParamMixin:
    """
    Миксин для добавления закодированных GET-параметров в контекст шаблона.
    Используется для сохранения поиска при пагинации.
    """

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        query_params = self.request.GET.copy()
        query_params.pop('page', None)
        encode_params = query_params.urlencode()

        context['query_params'] = encode_params

        return context
