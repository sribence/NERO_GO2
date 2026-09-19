FROM python:3.11-slim
WORKDIR /app
COPY core/ /app/core/
COPY orchestration/requirements.txt /app/orchestration/requirements.txt
RUN pip install --no-cache-dir -r /app/core/requirements.txt -r /app/orchestration/requirements.txt
COPY orchestration/ /app/orchestration/
ENV PYTHONPATH=/app/core:/app/orchestration
WORKDIR /app/orchestration
CMD ["python", "app.py"]
