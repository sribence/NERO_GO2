FROM python:3.11-slim
WORKDIR /app
COPY core/ /app/core/
COPY audio/requirements.txt /app/audio/requirements.txt
RUN pip install --no-cache-dir -r /app/core/requirements.txt -r /app/audio/requirements.txt
COPY audio/ /app/audio/
ENV PYTHONPATH=/app/core:/app/audio
WORKDIR /app/audio
CMD ["python", "app.py"]
