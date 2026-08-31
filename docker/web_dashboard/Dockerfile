# NERO_GO2 web dashboard — szeparált a robot natív rendszerétől.
# Ld. ../../docs/00-BIZTONSAGI-SZABALYOK.md
#
# FIGYELEM: ez a Dockerfile jelenleg NEM teljes — az unitree_sdk2py
# telepítése hiányzik (ld. requirements.txt megjegyzés), ezt holnap,
# a robotnál kell befejezni és tesztelni.

FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# TODO: unitree_sdk2py telepítése/vendorolása ide

COPY app.py .
COPY templates/ templates/

EXPOSE 5002

CMD ["python", "app.py"]
