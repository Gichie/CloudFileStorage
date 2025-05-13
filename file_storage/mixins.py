from django.urls import reverse_lazy

from file_storage.models import UserFile


class StorageSuccessUrlMixin:
    """Миксин для формирования URL перенаправления после успешных операций с файлами и папками"""
    def get_success_url(self):
        parent = self.object.parent
        if parent:
            return f"{reverse_lazy('file_storage:list_files')}?path={parent.get_path_for_url()}"
        return reverse_lazy('file_storage:list_files')


class UserFormKwargsMixin:
    """Миксин для передачи текущего пользователя в качестве аргумента в форму"""

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs


class ParentInitialMixin:
    """
    Миксин для предварительного выбора родительской папки в форме
    на основе параметра 'folder' в URL.
    """

    def get_initial(self):
        initial = super().get_initial()
        folder_id = self.request.GET.get('folder')
        if folder_id:
            try:
                folder = UserFile.objects.get(
                    id=folder_id, user=self.request.user, object_type='directory'
                )
                initial['parent'] = folder
            except UserFile.DoesNotExist:
                pass
        return initial
