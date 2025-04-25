from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render
from django.views.generic import TemplateView


class HomeView(LoginRequiredMixin, TemplateView):
    template_name = 'file_storage/home.html'
