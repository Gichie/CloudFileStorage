FROM python:3.13-slim
RUN groupadd -r groupdjango && useradd -r -g groupdjango userdj

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONNUNBUFFERED=1

RUN pip install --upgrade pip

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN mkdir -p /app/logs && \
    touch /app/logs/logs.log && \
    chown -R userdj:groupdjango /app/logs && \
    chmod -R 755 /app/logs

USER userdj