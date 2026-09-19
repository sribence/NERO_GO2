FROM python:3.11-slim
WORKDIR /app
COPY core/ /app/core/
COPY blackbox/requirements.txt /app/blackbox/requirements.txt
RUN pip install --no-cache-dir -r /app/core/requirements.txt -r /app/blackbox/requirements.txt
COPY blackbox/ /app/blackbox/
ENV PYTHONPATH=/app/core:/app/blackbox
WORKDIR /app/blackbox
CMD ["python", "app.py"]
