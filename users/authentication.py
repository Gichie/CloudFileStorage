from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import User
from django.http import HttpRequest


class EmailAuthBackend(BaseBackend):
    """
    Бэкенд аутентификации по адресу электронной почты.

    Позволяет пользователям входить в систему, используя свой email
    вместо имени пользователя.
    """

    user_model = get_user_model()

    def authenticate(
            self,
            request: HttpRequest | None,
            **kwargs: Any
    ) -> User | None:
        """
        Аутентифицирует пользователя по email и паролю.

        :param request: Объект HttpRequest.
        :param username: Имя пользователя (в данном случае используется как email).
        :param password: Пароль пользователя.
        :param kwargs: Дополнительные аргументы.
        :return: Объект пользователя в случае успеха, иначе None.
        """
        username = kwargs.get('username')
        password = kwargs.get('password')

        if not isinstance(username, str) or not isinstance(password, str):
            return None

        try:
            user = self.user_model.objects.get(email__iexact=username)

            if user.check_password(password):
                return user
            return None
        except (self.user_model.DoesNotExist, self.user_model.MultipleObjectsReturned):
            return None

    def get_user(self, user_id: int) -> User | None:
        """
        Получает объект пользователя по его ID.

        Этот метод необходим для работы сессионного фреймворка Django.

        :param user_id: Первичный ключ пользователя.
        :return: Объект пользователя или None, если не найден.
        """
        try:
            return self.user_model.objects.get(pk=user_id)
        except self.user_model.DoesNotExist:
            return None
