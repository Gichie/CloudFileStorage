from .base import *  # noqa

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False

ALLOWED_HOSTS = ['84.54.56.10']

SESSION_REDIS_URL = "redis://redis:6379/0"

# Настроки minio
AWS_S3_ENDPOINT_URL = 'http://minio:9000'  # URL Minio сервера
AWS_S3_CUSTOM_DOMAIN = f'84.54.56.10:9000'
AWS_QUERYSTRING_AUTH = True
AWS_S3_ADDRESSING_STYLE = 'path'
