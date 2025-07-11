FROM python:3.13-slim

# Устанавливаем переменные окружения
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Объявляем ARG, который можно будет передать при сборке
ARG DJANGO_SETTINGS_MODULE

# Устанавливаем переменную окружения для всех команд в Dockerfile
ENV DJANGO_SETTINGS_MODULE=$DJANGO_SETTINGS_MODULE

# Создаем пользователя, но пока не переключаемся на него
RUN groupadd -r groupdjango && useradd --no-create-home --shell /bin/false -r -g groupdjango userdj

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

WORKDIR /app

RUN mkdir -p /app/logs

COPY . .

RUN mkdir -p /app/staticfiles && \
    mkdir -p /app/mediafiles && \
    chown -R userdj:groupdjango /app/staticfiles && \
    chown -R userdj:groupdjango /app/mediafiles

# Передаем владение всем кодом нашему пользователю
RUN chown -R userdj:groupdjango /app
USER userdj