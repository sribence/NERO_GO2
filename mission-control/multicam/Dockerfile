FROM python:3.11-slim
WORKDIR /app
COPY core/ /app/core/
COPY multicam/requirements.txt /app/multicam/requirements.txt
RUN pip install --no-cache-dir -r /app/core/requirements.txt -r /app/multicam/requirements.txt
COPY multicam/ /app/multicam/
ENV PYTHONPATH=/app/core:/app/multicam
WORKDIR /app/multicam
CMD ["python", "app.py"]
