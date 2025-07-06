import pytest


@pytest.mark.django_db(transaction=True)
class BaseIntegrationTestCase:
    """Базовый класс-миксин для тестов. Автоматически применяет маркер для работы с БД."""

    pass
