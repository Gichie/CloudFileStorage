import json
import logging
import urllib

from botocore.exceptions import ClientError, ParamValidationError
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse, HttpResponseRedirect, StreamingHttpResponse, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView

from cloud_file_storage import settings
from file_storage.exceptions import NameConflictError
from file_storage.forms import FileUploadForm, DirectoryCreationForm
from file_storage.models import UserFile, FileType
from file_storage.utils import ui, path_utils, directory_utils, file_upload_utils
from file_storage.utils.archive_service import ZipStreamGenerator
from file_storage.utils.file_upload_utils import get_message_and_status
from file_storage.utils.minio import minio_storage

logger = logging.getLogger(__name__)


class FileListView(LoginRequiredMixin, ListView):
    model = UserFile
    template_name = 'file_storage/list_files.html'
    context_object_name = 'items'

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.user = self.request.user
        path_param_encoded = self.request.GET.get('path')

        self.current_directory, self.current_path_unencoded = path_utils.parse_directory_path(self.user,
                                                                                              path_param_encoded)

    def get_queryset(self):
        if self.current_directory:
            queryset = UserFile.objects.filter(user=self.user, parent=self.current_directory)
            logger.info(f"User '{self.user.username}': Successfully resolved path '{self.current_path_unencoded}'")
        else:
            queryset = UserFile.objects.filter(user=self.user, parent=None)
            logger.info(
                f"User '{self.user.username}': "
                f"Listing root directory contents (no specific path or path resolved to root)."
            )

        return queryset.order_by('object_type', 'name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['current_directory'] = self.current_directory
        context['current_path_unencoded'] = self.current_path_unencoded

        context['breadcrumbs'] = ui.generate_breadcrumbs(self.current_directory, self.current_path_unencoded)

        # Формирование URL для кнопки "Назад"
        context['parent_level_url'] = ui.get_parent_url(
            self.current_directory, 'file_storage:list_files'
        )

        context['current_folder_id'] = self.current_directory.id if self.current_directory else None

        if 'form_create_folder' not in context:
            context['form_create_folder'] = DirectoryCreationForm(user=self.user)

        return context

    def post(self, request, *args, **kwargs):
        """Обработка создания новой папки"""
        form = DirectoryCreationForm(request.POST, user=request.user)
        if form.is_valid():
            parent_pk = request.POST.get('parent')
            parent_object = None

            if parent_pk:
                parent_object = directory_utils.get_parent_directory(self.user, parent_pk)
                if isinstance(parent_object, JsonResponse):
                    return parent_object

            directory_name = form.cleaned_data['name']

            if directory_utils.directory_exists(self.user, directory_name, parent_object):
                logger.warning(
                    f"User {request.user.username}: Directory: {directory_name} "
                    f"already exists in parent '{parent_object.name if parent_object else 'root'}'."
                )
                return JsonResponse({
                    'status': 'error',
                    'message': f"Файл или папка с именем '{directory_name}' уже существует в текущей директории."
                }, status=400)

            result = minio_storage.create_directory(self.user, directory_name, parent_object)

            if result['success']:
                return JsonResponse({
                    'status': 'success',
                    'message': 'Папка успешно создана!',
                    'directory': {
                        'id': result['directory'].id,
                        'name': result['directory'].name,
                        'type': FileType.DIRECTORY.value,
                        'icon_class': 'bi-folder-fill',
                    }
                })
            return JsonResponse({
                'status': 'error',
                'message': result['message']
            }, status=result['status'])

        else:
            logger.warning(
                f"User '{self.user.username}': Form validation failed. "
                f"Errors: {json.dumps(form.errors.get_json_data(escape_html=False), ensure_ascii=False)}"
            )
            return JsonResponse(
                {'status': 'error', 'message': f'{form.errors["name"][0]}', 'errors': form.errors.as_json()},
                status=400
            )


class FileUploadAjaxView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        files = request.FILES.getlist('files') or request.FILES.getlist('file')
        relative_path = request.POST.get('relative_path')
        parent_id = request.POST.get('parent_id')
        user = request.user

        logger.info(
            f"{self.__class__.__name__}: User '{user.username}' ID: {user.id} initiated file upload. "
            f"Target parent_id: '{parent_id}'."
        )

        if not files:
            logger.warning(f"User '{user.username}': File upload request received without files.")
            return JsonResponse({'error': 'Файл отсутствует'}, status=400)

        parent_object = directory_utils.get_parent_directory(user, parent_id)
        if isinstance(parent_object, JsonResponse):
            return parent_object

        results = []
        for uploaded_file in files:
            form_data = {'parent': parent_object.pk if parent_object else None}
            form_files = {'file': uploaded_file}
            form = FileUploadForm(form_data, form_files, user=user)

            if form.is_valid():
                try:
                    result = file_upload_utils.handle_file_upload(
                        uploaded_file, user, parent_object, relative_path
                    )
                    results.append(result)
                except NameConflictError as e:
                    results.append({
                        'name': e.name,
                        'status': 'error',
                        'error': e.get_message(),
                    })
                except Exception as e:
                    logger.critical(
                        f"User '{user.username}': Critical unhandled error in _handle_file_upload "
                        f"for file '{uploaded_file.name}': {e}",
                        exc_info=True
                    )
                    results.append({
                        'name': uploaded_file.name,
                        'status': 'error',
                        'error': 'Внутренняя ошибка сервера при загрузке файла',
                    })
            else:
                error_messages = []
                for field, errors in form.errors.items():
                    error_messages.append(f"{field}: {'; '.join(errors)}")
                error_string = "; ".join(error_messages)
                logger.warning(
                    f"User '{user.username}': File '{uploaded_file.name}' failed validation. "
                    f"Errors: {error_string}"
                )
                results.append({
                    'name': uploaded_file.name,
                    'status': 'error',
                    'error': error_string or 'Ошибка валидации файла.'
                })

        response_data, status_code = get_message_and_status(results)
        return JsonResponse(response_data, status=status_code)


class DownloadFileView(LoginRequiredMixin, View):
    def get(self, request, file_id):
        user_file = get_object_or_404(
            UserFile, id=file_id, user=request.user, object_type=FileType.FILE
        )

        s3_key = user_file.file.name

        try:
            presigned_url = minio_storage.s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': settings.AWS_STORAGE_BUCKET_NAME,
                    'Key': s3_key,
                    'ResponseContentDisposition': f'attachment; filename="{user_file.name}"'
                },
                ExpiresIn=1800
            )
            logger.info(f"File downloaded successfully. s3_key: {s3_key}, presigned_url: {presigned_url}")
            return HttpResponseRedirect(presigned_url)
        except ClientError as e:
            logger.error(f"Error generating presigned URL for s3_key: {s3_key}: {e}")
            messages.error(request, "Произошла ошибка при обращении к хранилищу, попробуйте позже")
            return redirect(f'file_storage:list_files')
        except ParamValidationError as e:
            logger.error(f"{e}")
            messages.error(request, "Произошла ошибка при запросе к хранилищу")
            return redirect(f'file_storage:list_files')
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            messages.error(request, "Произошла ошибка при скачивании файла, попробуйте позже")
            return redirect(f'file_storage:list_files')


class DownloadDirectoryView(LoginRequiredMixin, View):
    def get(self, request, directory_id):
        directory = get_object_or_404(
            UserFile, id=directory_id, user=request.user, object_type=FileType.DIRECTORY
        )
        try:
            zip_generator = ZipStreamGenerator(directory)

            zip_filename = f"{directory.name}.zip"
            encoded_zip_filename = urllib.parse.quote(zip_filename)

            response = StreamingHttpResponse(
                zip_generator.generate(), content_type='application/zip'
            )

            response['Content-Disposition'] = f'attachment; filename="{encoded_zip_filename}"'
            response['Cache-Control'] = 'no-cache'

            logger.info(f"User '{request.user.username}' started "
                        f"downloading directory '{directory.name}' "
                        f"as '{zip_filename}'.")
            return response
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            messages.error(request, "Произошла ошибка при подготовке архива, попробуйте позже")
            return redirect(f'file_storage:list_files')


class FileSearchView(LoginRequiredMixin, View):
    template_name = 'file_storage/search_results.html'

    def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        context = {}
        query = request.GET.get('query', None)
        context['query'] = query
        if query:
            search_results = UserFile.objects.filter(
                user=request.user, name__icontains=query
            ).order_by('object_type', 'name')
        else:
            search_results = None
        context['search_results'] = search_results

        return render(request, self.template_name, context)


class DeleteView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        return HttpResponse("Удаление выполнено", status=200)


class RenameView(LoginRequiredMixin, ListView):
    pass
