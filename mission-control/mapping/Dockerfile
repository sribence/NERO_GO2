FROM python:3.11-slim
WORKDIR /app
COPY core/ /app/core/
COPY mapping/requirements.txt /app/mapping/requirements.txt
RUN pip install --no-cache-dir -r /app/core/requirements.txt -r /app/mapping/requirements.txt
COPY mapping/ /app/mapping/
ENV PYTHONPATH=/app/core:/app/mapping
WORKDIR /app/mapping
CMD ["python", "app.py"]
