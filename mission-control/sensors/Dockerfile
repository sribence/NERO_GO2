FROM python:3.11-slim
WORKDIR /app
COPY core/ /app/core/
COPY sensors/requirements.txt /app/sensors/requirements.txt
RUN pip install --no-cache-dir -r /app/core/requirements.txt -r /app/sensors/requirements.txt
COPY sensors/ /app/sensors/
ENV PYTHONPATH=/app/core:/app/sensors
WORKDIR /app/sensors
CMD ["python", "app.py"]
