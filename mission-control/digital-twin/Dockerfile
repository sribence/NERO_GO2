FROM python:3.11-slim
WORKDIR /app
COPY core/ /app/core/
COPY digital-twin/requirements.txt /app/digital-twin/requirements.txt
RUN pip install --no-cache-dir -r /app/core/requirements.txt -r /app/digital-twin/requirements.txt
COPY digital-twin/ /app/digital-twin/
ENV PYTHONPATH=/app/core:/app/digital-twin
WORKDIR /app/digital-twin
CMD ["python", "server.py"]
