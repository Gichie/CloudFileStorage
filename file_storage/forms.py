import os
import re

from django import forms

from file_storage.models import UserFile, FileType

INVALID_CHARS_PATTERN = re.compile(r'[\/\\<>:"|?*]')
MAX_FILE_SIZE = 200 * 1024 * 1024  # 200 МБ

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
            if file.size > MAX_FILE_SIZE:
                raise forms.ValidationError("Файл слишком большой. Максимальный размер - 200 МБ.")
            return file
        else:
            raise forms.ValidationError("Файл отсутствует или его не удалось прочитать.")


class DirectoryCreationForm(forms.ModelForm):
    parent = forms.ModelChoiceField(
        queryset=UserFile.objects,
        required=False,
        widget=forms.HiddenInput(),
    )

    class Meta:
        model = UserFile
        fields = ['name', 'parent']

        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
            }),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if self.user:
            self.fields['parent'].queryset = UserFile.objects.filter(
                user=self.user, object_type=FileType.DIRECTORY
            )
            self.fields['name'].required = True

    def clean_name(self):
        name = self.cleaned_data.get('name')
        if INVALID_CHARS_PATTERN.search(name):
            raise forms.ValidationError("Имя папки не может содержать символы: / \\ < > : \" | ? *")
        if name == '.':
            raise forms.ValidationError("Имя папки не может быть '.'")
        if name.endswith('.') or name.startswith('.'):
            raise forms.ValidationError("Имя папки не может начинаться или оканчиваться на '.'")
        return name
