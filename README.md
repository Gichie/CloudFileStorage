# CloudFileStorage - Облачное хранилище файлов

[![Python Version](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/release/python-3130/)
[![Django Version](https://img.shields.io/badge/django-5.0-green.svg)](https://www.djangoproject.com/download/)

Учебный проект в рамках roadmap'а [Python Backend Developer](https://zhukovsd.github.io/python-backend-learning-course/projects/cloud-file-storage/).

## Основные возможности

*   **Аутентификация и авторизация**: Регистрация, вход, выход из системы. Каждый пользователь имеет доступ только к своим файлам.
*   **Управление файлами**: Загрузка, скачивание, переименование и удаление файлов.
*   **Управление папками**: Создание, переименование и удаление папок с поддержкой вложенности.
*   **Навигация**: Иерархическая структура папок ("хлебные крошки").
*   **Поиск**: Поиск по файлам и папкам в текущей директории.
*   **Просмотр**: Отображение информации о файле (размер, дата загрузки).

## Стек технологий

| Категория           | Технология                                      |
| ------------------- | ----------------------------------------------- |
| **Backend**         | Python 3.13, Django 5, Gunicorn                 |
| **Базы данных**     | PostgreSQL                                      |
| **Кэш (сессии)**    | Redis                                           |
| **Файловое хранилище**| MinIO (S3-совместимое)                          |
| **Фронтенд**        | HTML5, CSS3, Bootstrap 5, JavaScript            |
| **Тестирование**    | Pytest, pytest-django                           |
| **Инструменты**     | Docker, Docker Compose, Flake8                  |

## Установка и запуск

Проект полностью контейнеризирован, для запуска требуется только Docker и Docker Compose.

1.  **Клонируйте репозиторий:**
    ```bash
    git clone https://github.com/Gichie/CloudFileStorage.git
    cd CloudFileStorage
    ```

2.  **Создайте файл `.env`:** и заполните своими данными
    ```bash
    nano .env
    ```
    Содержимое файла .env.

```env
# Django settings
SECRET_KEY=your-super-secret-key-here

DJANGO_SETTINGS_MODULE=cloud_file_storage.settings.local

# Postgres settings
POSTGRES_DB=cloud_db
POSTGRES_USER=cloud_user
POSTGRES_PASSWORD=cloud_password
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

# MinIO/S3 settings
MINIO_ROOT_USER=RsEHteEk
MINIO_ROOT_PASSWORD=MwCNJgFo
AWS_ACCESS_KEY_ID=RsEHteEk
AWS_SECRET_ACCESS_KEY=MwCNJgFo
```

3.  **Соберите и запустите контейнеры:**
    ```bash
    docker compose -f docker-compose-services.yml up --build -d
    ```
    
4.  **Создайте и активируйте виртуальное окружение:**
    ```bash
    python -m venv venv
    source venv/Scripts/activate
    ```
    
5.  **Установите зависимости:**
    ```bash
    pip install -r requirements.txt
    ```    

6.  **Примените миграции:**
    ```bash
    python manage.py migrate
    ```
7.  **Запустите приложение:**
    ```bash
    python manage.py runserver
    ```
8.  Проект будет доступен по адресу: `http://localhost:8000`

9.  Веб-интерфейс MinIO будет доступен по адресу: `http://localhost:9001` (используйте `MINIO_ROOT_USER` и `MINIO_ROOT_PASSWORD` для входа).

10.  Создайте в MinIO бакет с названием `file-storage-bucket`