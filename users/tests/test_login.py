from importlib import import_module

import time

from django.contrib.auth import get_user_model, SESSION_KEY, BACKEND_SESSION_KEY, HASH_SESSION_KEY

from django.test import override_settings
from django.urls import reverse
from freezegun import freeze_time
from test_plus.plugin import TestCase
import pytest
from django.conf import settings
from users.forms import LoginUserForm

User = get_user_model()


@pytest.mark.django_db
class TestLogin(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.signup_url = reverse('users:registration')
        cls.login_url = reverse('users:login')
        cls.logout_url = reverse('users:logout')
        cls.home_url = reverse('file_storage:list_files')
        cls.valid_username = 'testuser'
        cls.valid_password = 'testpass123'
        cls.valid_email = 'test@sobaka.gav'
        cls.valid_login_data = {'username': cls.valid_username, 'password': cls.valid_password}
        cls.user = User.objects.create_user(username=cls.valid_username, password=cls.valid_password)

    def test_login_view_get(self):
        """Тест: Доступность страницы входа (GET)."""
        response = self.client.get(self.login_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'users/login.html')
        self.assertContains(response, 'Авторизация')
        self.assertIsInstance(response.context['form'], LoginUserForm)
        # Проверка отсутствия ошибок
        self.assertEqual(response.context['form'].errors, {})
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_successful_login_creates_session(self):
        self.assertNotIn(SESSION_KEY, self.client.session)

        response = self.client.post(self.login_url, self.valid_login_data)

        self.assertRedirects(response, self.home_url, 302)
        self.assertIn(SESSION_KEY, self.client.session)
        self.assertIn(BACKEND_SESSION_KEY, self.client.session)
        self.assertIn(HASH_SESSION_KEY, self.client.session)
        self.assertEqual(self.client.session[SESSION_KEY], str(self.user.pk))

    def test_unsuccessful_login_invalid_password(self):
        self.assertNotIn(SESSION_KEY, self.client.session)

        invalid_login_data = {'username': self.valid_username, 'password': 'invalid_password'}
        response = self.client.post(self.login_url, invalid_login_data)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'users/login.html')
        expected_error = 'Пожалуйста, введите правильные имя пользователя и пароль. Оба поля могут быть чувствительны к регистру.'
        self.assertContains(response, expected_error)
        self.assertTrue(response.context['form'].non_field_errors())
        self.assertEqual(response.context['form'].non_field_errors()[0], expected_error)
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertNotIn(BACKEND_SESSION_KEY, self.client.session)
        self.assertNotIn(HASH_SESSION_KEY, self.client.session)

    def test_unsuccessful_login_non_exist_user(self):
        self.assertNotIn(SESSION_KEY, self.client.session)

        invalid_login_data = {'username': 'non_exist_username', 'password': 'non_exist_password'}
        response = self.client.post(self.login_url, invalid_login_data)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'users/login.html')
        expected_error = 'Пожалуйста, введите правильные имя пользователя и пароль. Оба поля могут быть чувствительны к регистру.'
        self.assertContains(response, expected_error)
        self.assertTrue(response.context['form'].non_field_errors())
        self.assertEqual(response.context['form'].non_field_errors()[0], expected_error)
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertNotIn(BACKEND_SESSION_KEY, self.client.session)
        self.assertNotIn(HASH_SESSION_KEY, self.client.session)

    def test_logout_delete_session(self):
        """Тест: Выход из системы удаляет сессию."""
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.client.post(self.login_url, self.valid_login_data)
        self.assertIn(SESSION_KEY, self.client.session)

        response = self.client.post(self.logout_url)

        self.assertRedirects(response, self.login_url, status_code=302, fetch_redirect_response=True)

        self.assertNotIn(SESSION_KEY, self.client.session)

    @override_settings(
        SESSION_ENGINE='django.contrib.sessions.backends.db',
        SESSION_COOKIE_AGE=60,
        SESSION_EXPIRE_AT_BROWSER_CLOSE=False,
    )
    @freeze_time("2022-02-24 11:00:00")
    def test_session_expiry_with_db_backend(self):
        """Тест: Проверка, что сессия истекает согласно настройкам. Используется локальная БД."""
        self.client.post(self.login_url, self.valid_login_data)

        session_key = self.client.session.session_key

        # пролистываем время на 61 секунду
        with freeze_time("2022-02-24 11:01:01"):
            # грузим сессию напрямую из DB
            engine = import_module(settings.SESSION_ENGINE)
            store = engine.SessionStore(session_key)
            data = store.load()
            # в DB-бэкенде freezegun «передвинул» now() вперёд, так что сессия уже должна быть пуста
            self.assertNotIn(SESSION_KEY, data)

    @override_settings(SESSION_COOKIE_AGE=1)
    def test_session_expiry_by_redis_sessions(self):
        self.client.post(self.login_url, self.valid_login_data)

        response = self.client.get(self.home_url)
        self.assertEqual(response.status_code, 200)

        # Ждем, пока сессия истечет (1 секунда + небольшой буфер)
        time.sleep(2)

        # Проверяем, что сессия истекла
        response = self.client.get(self.home_url)
        self.assertEqual(response.status_code, 302)  # Например, редирект на логин

