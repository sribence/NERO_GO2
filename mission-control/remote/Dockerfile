# remote/Dockerfile -- log_shipper.py only. No core/ dependency (it talks
# to blackbox over HTTP, not to the robot directly), so this is a smaller
# image than the CONVENTIONS.md core+pillar pattern -- there is no robot
# client import here to justify pulling core/ in.
FROM python:3.11-slim
WORKDIR /app
COPY remote/requirements.txt /app/remote/requirements.txt
RUN pip install --no-cache-dir -r /app/remote/requirements.txt
COPY remote/log_shipper.py /app/remote/log_shipper.py
WORKDIR /app/remote
CMD ["python", "log_shipper.py"]
