from django.urls import path

app_name = 'users'

urlpatterns = [
    path('login/', views.LoginUser.as_view(), name='login'),
    path('logout/', views.LogoutUser.as_view(), name='logout'),
    path('registration/', views.RegistrationUser.as_view(), name='registration'),
]