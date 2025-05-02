from django import forms

from file_storage.models import UserFile


class FileUploadForm(forms.ModelForm):
    class Meta:
        model = UserFile
        fields = ['file']

    def clean_file(self):
        file = self.cleaned_data.get('file')
        if file:
            # Валидация на размер файла(не больше 100 МБ)
            if file.size > 100 * 1024 * 1024:
                raise forms.ValidationError("Файл слишком большой. Максимальный размер - 100 МБ.")
            return file
        else:
            raise forms.ValidationError("Файл отсутствует или его не удалось прочитать.")
