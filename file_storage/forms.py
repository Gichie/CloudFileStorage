import os
import re

from django import forms

from file_storage.models import UserFile

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
            # Валидация на размер файла(не больше 100 МБ)
            if file.size > 100 * 1024 * 1024:
                raise forms.ValidationError("Файл слишком большой. Максимальный размер - 100 МБ.")
            return file
        else:
            raise forms.ValidationError("Файл отсутствует или его не удалось прочитать.")


class DirectoryCreationForm(forms.ModelForm):
    class Meta:
        model = UserFile
        fields = ['name', 'parent']

        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Введите название папки'
            }),
            'parent': forms.Select(attrs={
                'class': 'form-control'
            }),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if user:
            self.fields['parent'].queryset = UserFile.objects.filter(
                user=user, object_type='directory'
            )
            self.fields['parent'].required = False
            self.fields['parent'].empty_label = "Корневая директория"

    def clean_name(self):
        name = self.cleaned_data.get('name')
        if INVALID_CHARS_PATTERN.search(name):
            raise forms.ValidationError("Имя папки не может содержать символы: / \\ < > : \" | ? *")
        if name == '.':
            raise forms.ValidationError("Имя папки не может быть '.'")
        if name.endswith('.') or name.startswith('.'):
            raise forms.ValidationError("Имя папки не может начинаться или оканчиваться на '.'")
        return name
