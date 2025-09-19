FROM python:3.11-slim

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Создание рабочей директории
WORKDIR /app

# Копирование файлов зависимостей
COPY requirements.txt .

# Установка Python зависимостей
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода приложения
COPY config.py .
COPY main.py .
COPY sync.py .
COPY utils.py .

# Создание директории для логов с правильными правами
RUN mkdir -p /app/logs && chmod 755 /app/logs

# Пользователь для безопасности
RUN useradd -m -u 1000 syncuser && \
    chown -R syncuser:syncuser /app

USER syncuser

# Команда по умолчанию
CMD ["python", "main.py"] 
