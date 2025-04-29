from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.files.storage import default_storage
from django.shortcuts import redirect, render
from django.views.generic import TemplateView

from file_storage.forms import FileUploadForm
from file_storage.models import UserFile


class HomeView(LoginRequiredMixin, TemplateView):
    template_name = 'file_storage/list_files.html'


@login_required
def upload_file(request):
    from django.conf import settings
    minio_settings = {
        'DEFAULT_FILE_STORAGE': getattr(settings, 'DEFAULT_FILE_STORAGE', 'Не задано'),
        'AWS_ACCESS_KEY_ID': getattr(settings, 'AWS_ACCESS_KEY_ID', 'Не задано'),
        'AWS_SECRET_ACCESS_KEY': getattr(settings, 'AWS_SECRET_ACCESS_KEY', 'Не задано') != 'Не задано',
        'AWS_STORAGE_BUCKET_NAME': getattr(settings, 'AWS_STORAGE_BUCKET_NAME', 'Не задано'),
        'AWS_S3_ENDPOINT_URL': getattr(settings, 'AWS_S3_ENDPOINT_URL', 'Не задано'),
    }
    print("Настройки Minio:", minio_settings)

    if request.method == "GET":
        form = FileUploadForm()
    else:
        form = FileUploadForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = request.FILES['file']

            # Проверяем, какое хранилище используется

            print(f"Используемое хранилище: {default_storage.__class__.__name__}")

            # Если видим FileSystemStorage, показываем подробную информацию
            if default_storage.__class__.__name__ == 'FileSystemStorage':
                print("ВНИМАНИЕ! Используется локальное хранилище!")
                print(f"DEFAULT_FILE_STORAGE в settings: {getattr(settings, 'DEFAULT_FILE_STORAGE', 'Не задано')}")

            # Создаем экземпляр модели
            user_file_instance = UserFile(
                user=request.user,
                file=uploaded_file
            )

            # Сохраняем модель (файл будет сохранен автоматически)
            user_file_instance.save()

            # Получаем путь к сохраненному файлу
            saved_path = user_file_instance.file.name
            print(f"Файл сохранен по пути: {saved_path}")

            # Получаем URL файла
            file_url = user_file_instance.file.url
            print(f"URL сохраненного файла: {file_url}")

            return redirect('file_storage:list_files')

    return render(request, 'file_storage/upload_file.html', {'form': form})


@login_required
def list_files(request):
    user_files = UserFile.objects.filter(user=request.user).order_by('-uploaded_at')
    return render(request, 'file_storage/list_files.html', {'files': user_files})
