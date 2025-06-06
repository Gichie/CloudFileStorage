from django.contrib.auth.views import LoginView
from django.contrib.messages.views import SuccessMessageMixin
from django.shortcuts import render
from django.urls import reverse_lazy
from django.views.generic import CreateView

from users.forms import LoginUserForm, RegistrationForm


class LoginUser(LoginView):
    form_class = LoginUserForm
    template_name = 'users/login.html'
    extra_context = {'title': 'Авторизация'}


class RegistrationUser(SuccessMessageMixin, CreateView):
    form_class = RegistrationForm
    template_name = 'users/registration.html'
    extra_context = {'title': 'Регистрация'}
    success_url = reverse_lazy('users:login')
    success_message = 'Регистрация прошла успешно!'
