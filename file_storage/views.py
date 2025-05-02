from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.shortcuts import render
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView

from file_storage.forms import FileUploadForm
from file_storage.models import UserFile


class HomeView(LoginRequiredMixin, ListView):
    template_name = 'file_storage/list_files.html'
    context_object_name = 'files'

    def get_queryset(self):
        files = UserFile.objects.filter(user=self.request.user)
        return files


class FileUploadView(LoginRequiredMixin, CreateView):
    model = UserFile
    form_class = FileUploadForm
    template_name = 'file_storage/upload_file.html'
    success_url = reverse_lazy('file_storage:list_files')

    def form_valid(self, form):
        form.instance.user = self.request.user
        try:
            with transaction.atomic():
                response = super().form_valid(form)
                messages.success(self.request, "Файл успешно загружен")
                return response
        except Exception as e:
            messages.error(self.request, f"Ошибка при загрузке файла: {str(e)}")
            return self.form_invalid(form)

    def form_invalid(self, form):
        messages.error(self.request, "Ошибка при загрузке файла")
        return super().form_invalid(form)
