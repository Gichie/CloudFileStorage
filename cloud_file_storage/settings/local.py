from .base import *

DEBUG = True

ALLOWED_HOSTS = ['localhost', '127.0.0.1']

SESSION_REDIS_URL = "localhost://redis:6379/0"

# Настроки minio
AWS_S3_ENDPOINT_URL = 'http://localhost:9000'  # URL Minio сервера
AWS_S3_CUSTOM_DOMAIN = f'localhost:9000/{AWS_STORAGE_BUCKET_NAME}'
AWS_QUERYSTRING_AUTH = False  # Отключает параметры аутентификации в URL

SESSION_REDIS = {
    'host': 'localhost',  # для локали
    'port': 6379,
    'db': 0,
    'password': None,
    'prefix': 'session',
}
