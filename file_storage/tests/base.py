import pytest
from test_plus.plugin import TestCase


@pytest.mark.django_db
class BaseIntegrationTestCase(TestCase):
    """
    Базовый класс для всех интеграционных тестов в приложении.

    Он автоматически применяет фикстуры для настройки БД и внешних сервисов (S3).
    Наследуется от TestCase.
    """

    pass
