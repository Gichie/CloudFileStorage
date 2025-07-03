import logging
from typing import Any

from django.contrib.auth.models import User
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.http import HttpRequest

logger = logging.getLogger(__name__)


def get_client_ip(request: HttpRequest) -> str:
    """
    Получает IP-адрес клиента из запроса.

    Приоритет отдается заголовку HTTP_X_FORWARDED_FOR, так как
    приложение может работать за прокси-сервером или балансировщиком.

    :param request: Объект HttpRequest.
    :return: Строка с IP-адресом клиента.
    """
    x_forarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forarded_for:
        ip = x_forarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


@receiver(user_logged_in)
def log_user_logged_in(sender, request: HttpRequest, user: User, **kwargs) -> None:
    """Логирует успешный вход пользователя."""
    ip = get_client_ip(request)
    logger.info(f"Успешный вход: Пользователь '{user}' (ID: {user.id}) вошел с IP: {ip}")


@receiver(user_login_failed)
def log_user_login_failed(sender, credentials: dict[str, Any], request: HttpRequest, **kwargs) -> None:
    """Логирует неудачную попытку входа."""
    ip = get_client_ip(request)
    username = credentials.get('username', None)
    logger.warning(f"Неудачная попытка входа: Для пользователя '{username}' с IP: {ip}")


@receiver(post_save, sender=User)
def log_user_registered(sender, instance: User, created: bool, **kwargs) -> None:
    """Логирует создание нового пользователя."""
    if created:
        logger.info(
            f"Успешная регистрация: Новый пользователь '{instance.username}' "
            f"(ID: {instance.pk}) зарегистрирован.")
