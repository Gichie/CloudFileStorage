from typing import Any

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User


class LoginUserForm(AuthenticationForm):
    """
    Форма для аутентификации пользователей в системе.

    Позволяет войти, используя имя пользователя или адрес электронной почты.
    Наследуется от стандартной формы Django ``AuthenticationForm``,
    которая выполняет основную логику проверки учетных данных.
    """

    username = forms.CharField(
        label='Имя пользователя / E-mail',
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    password = forms.CharField(
        label='Пароль',
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )


class RegistrationForm(forms.ModelForm):
    """
    Форма для регистрации нового пользователя.

    Содержит поля для имени пользователя, e-mail и двойного ввода пароля для подтверждения.
    Наследуется от ``ModelForm`` для частичной привязки к модели ``User``.
    """

    username = forms.CharField(
        min_length=2,
        label='Имя пользователя',
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    password = forms.CharField(
        min_length=2,
        label='Пароль',
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )
    password2 = forms.CharField(
        label='Подтвердите пароль',
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )
    email = forms.EmailField(
        label='E-mail',
        required=False,
        widget=forms.EmailInput(attrs={'placeholder': 'Необязательно', 'class': 'form-control'})
    )

    class Meta:
        """
        Указывает, что форма работает с моделью User.

        Говорит ModelForm, что при вызове form.save() нужно попытаться сохранить
        значения из полей username и email в соответствующий объект модели User.
        """

        model = User
        fields = ('username', 'email')

    def clean_email(self) -> str | None:
        """
        Валидация и очистка поля email.

        Приводит email к нижнему регистру и проверяет его уникальность.
        """
        email = self.cleaned_data.get('email')
        if email:
            email = email.lower()
            if User.objects.filter(email=email).exists():
                raise forms.ValidationError('Такой E-mail уже существует')
        return email

    def clean(self) -> dict[str, Any] | None:
        """
        Общая валидация формы.

        Проверяет, совпадают ли введенные пароли.
        """
        form_data = super().clean()
        if form_data:
            password = form_data.get('password')
            password2 = form_data.get('password2')

            if password and password2 and password != password2:
                raise forms.ValidationError('Пароли не совпадают')

        return form_data

    def save(self, commit=True) -> User:
        """
        Сохраняет пользователя с хэшированным паролем.

        Переопределен для установки пароля через set_password.
        """
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])

        if commit:
            user.save()
        return user
