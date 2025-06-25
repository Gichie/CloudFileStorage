import os
import re
from typing import Any

from django import forms
from django.contrib.auth.models import User

from cloud_file_storage.settings import DATA_UPLOAD_MAX_MEMORY_SIZE
from file_storage.models import UserFile, FileType

INVALID_CHARS_PATTERN = re.compile(r'[\/\\<>:"|?*]')


class FileUploadForm(forms.ModelForm):
    class Meta:
        model = UserFile
        fields = ['name', 'file', 'parent']
        widgets = {'parent': forms.Select(attrs={'class': 'form-control'}), }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        self.fields['name'].widget = forms.HiddenInput()
        self.fields['name'].required = False
        self.fields['file'].allow_empty_file = True
        if user:
            self.fields['parent'].queryset = UserFile.objects.filter(
                user=user,
                object_type='directory'
            )
            self.fields['parent'].required = False
            self.fields['parent'].empty_label = "Корневая директория"

    def clean_file(self):
        file = self.cleaned_data.get('file')
        if file:
            if not self.cleaned_data.get('name'):
                self.cleaned_data['name'] = os.path.basename(file.name)
            if file.size > DATA_UPLOAD_MAX_MEMORY_SIZE:
                raise forms.ValidationError(
                    f"Файл слишком большой. "
                    f"Максимальный размер - {DATA_UPLOAD_MAX_MEMORY_SIZE} МБ."
                )
            return file
        else:
            raise forms.ValidationError("Файл отсутствует или его не удалось прочитать.")


class DirectoryCreationForm(forms.ModelForm):
    """
    Форма для создания новой директории.

    Позволяет пользователю указать имя для новой директории.
    Поле `parent` автоматически заполняется на основе текущей директории
    пользователя и скрыто в форме.
    """
    parent = forms.ModelChoiceField(
        queryset=UserFile.objects,
        required=False,
        widget=forms.HiddenInput(),
    )

    class Meta:
        model = UserFile
        fields: list[str] = ['name', 'parent']

        widgets: dict[str, Any] = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
            }),
        }

    def __init__(self, user: User, *args: Any, **kwargs: dict[str, Any]) -> None:
        """
        Инициализирует форму, устанавливая пользователя и фильтруя queryset для поля `parent`.

        Пользователь извлекается из `kwargs`.

        :param user: Пользователь.
        :param args: Позиционные аргументы для родительского конструктора.
        :param kwargs: Именованные аргументы. 'user' является обязательным.
        """
        self.user = user
        super().__init__(*args, **kwargs)

        if self.user:
            self.fields['parent'].queryset = UserFile.objects.filter(
                user=self.user, object_type=FileType.DIRECTORY
            )
            self.fields['name'].required = True

    def clean_name(self) -> str:
        """
        Валидирует имя директории.

        Проверяет, что имя не содержит запрещенных символов
        и что директория с таким именем еще не существует в текущей родительской директории
        для данного пользователя.

        :raises forms.ValidationError: Если имя некорректно или уже занято.
        :return: Очищенное имя директории.
        """
        name: str = self.cleaned_data.get('name', '').strip()
        if INVALID_CHARS_PATTERN.search(name):
            raise forms.ValidationError("Имя папки не может содержать символы: / \\ < > : \" | ? *")
        if name == '.':
            raise forms.ValidationError("Имя папки не может быть '.'")
        if name.endswith('.') or name.startswith('.'):
            raise forms.ValidationError("Имя папки не может начинаться или оканчиваться на '.'")
        return name


class RenameItemForm(forms.ModelForm):
    """
    Форма для валидации нового имени файла или папки.
    """
    class Meta:
        model = UserFile
        fields = ['name']

    def clean_name(self) -> str:
        """
        Валидирует новое имя объекта.

        Проверяет, что:
        - Новое имя не совпадает со старым.
        - Имя не пустое.
        - Имя не содержит недопустимых символов.
        - Имя не состоит из одних точек или не начинается/заканчивается на точку.

        :raises forms.ValidationError: Если имя не проходит валидацию.
        :return: Очищенное и валидное имя.
        """
        name: str = self.cleaned_data.get('name', '')
        if not name:
            raise forms.ValidationError("Новое имя не может быть пустым")
        if self.instance and self.instance.pk and self.instance.name == name:
            raise forms.ValidationError("Новое имя не должно совпадать со старым.")
        if not name:
            raise forms.ValidationError("Имя не может быть пустым.")
        if INVALID_CHARS_PATTERN.search(name):
            raise forms.ValidationError("Имя не может содержать символы: / \\ < > : \" | ? *")
        if name == '.':
            raise forms.ValidationError("Имя не может быть '.'")
        if name.endswith('.') or name.startswith('.'):
            raise forms.ValidationError("Имя не может начинаться или оканчиваться на '.'")

        return name
