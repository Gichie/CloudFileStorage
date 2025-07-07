import pytest
from django.contrib.auth import SESSION_KEY, get_user_model
from django.urls import reverse
from test_plus.test import TestCase

from users.forms import RegistrationForm

User = get_user_model()


@pytest.mark.django_db
class TestUserRegistration(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.signup_url = reverse('users:registration')
        cls.valid_username = 'testuser'
        cls.valid_password = 'testpass123'
        cls.valid_email = 'test@sobaka.gav'

    def test_registration_view_get(self):
        """Тест: Доступность страницы регистрации (GET)."""
        response = self.client.get(self.signup_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'users/registration.html')
        self.assertContains(response, 'Регистрация')
        self.assertIsInstance(response.context['form'], RegistrationForm)

    def test_successful_registration_creates_user(self):
        """Тест: Успешная регистрация создает новую запись User."""
        # Кол-во пользователей в БД до регистрации
        current_user_num = User.objects.count()
        sign_up_data = {
            'username': self.valid_username, 'email': self.valid_email,
            'password': self.valid_password, 'password2': self.valid_password,
        }

        response = self.client.post(self.signup_url, sign_up_data)

        # 1. Проверка редиректа
        self.assertRedirects(response, reverse("file_storage:list_files"), 302)

        # 2. Проверка создания пользователя в БД
        self.assertEqual(User.objects.count(), current_user_num + 1)
        new_user = User.objects.get(username=self.valid_username)
        self.assertEqual(new_user.email, self.valid_email)
        self.assertTrue(new_user.check_password(self.valid_password))
        self.assertFalse(new_user.is_staff)
        self.assertFalse(new_user.is_superuser)
        self.assertTrue(new_user.is_active)
        # Ключ сессии SESSION_KEY присутствует в текущей сессии пользователя.
        # Потому что пользователь только зарегистрировался и автоматически авторизовался.
        self.assertIn(SESSION_KEY, self.client.session)

    def test_unsuccessful_registration_creates_user(self):
        """Тест: Неуспешная регистрация"""
        # Кол-во пользователей в БД до регистрации
        current_user_num = User.objects.count()
        invalid_sign_up_data = {
            'username': self.valid_username, 'email': 'invalid-email',
            'password': '1', 'password2': 'invalid_password',
        }

        response = self.client.post(self.signup_url, invalid_sign_up_data)

        # Статус 200 (форма с ошибками) вместо редиректа
        self.assertEqual(response.status_code, 200)

        # Пользователь не создан
        self.assertEqual(User.objects.count(), current_user_num)
        # Проверка наличия ошибок в форме
        self.assertFalse(response.context['form'].is_valid())
        # Проверка наличия ключевых сообщений об ошибках
        form = response.context['form']
        self.assertIn('email', form.errors)
        self.assertIn('password', form.errors)

        self.assertNotIn(SESSION_KEY, self.client.session)
