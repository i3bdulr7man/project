# Dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY . /app

RUN pip install --upgrade pip && pip install -r requirements.txt

# (اختياري للأمان)

EXPOSE 8000

RUN pip install "gunicorn[uvicorn]"

ENV HUBSPOT_TOKEN=${HUBSPOT_TOKEN}
CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "-b", "0.0.0.0:8000"]
#CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
