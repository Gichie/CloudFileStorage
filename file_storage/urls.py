from django.urls import path

from file_storage.views import HomeView

app_name = 'file_storage'

urlpatterns = [
    path('', HomeView.as_view(), name='home'),
]
