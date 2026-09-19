FROM python:3.11-slim
WORKDIR /app
COPY core/ /app/core/
COPY navigation/requirements.txt /app/navigation/requirements.txt
RUN pip install --no-cache-dir -r /app/core/requirements.txt -r /app/navigation/requirements.txt
COPY navigation/ /app/navigation/
ENV PYTHONPATH=/app/core:/app/navigation
WORKDIR /app/navigation
CMD ["python", "app.py"]
