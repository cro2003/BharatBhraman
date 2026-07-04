FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app
COPY static /app/static
COPY templates /app/templates
COPY run.py /app/run.py

EXPOSE 8000

CMD ["gunicorn", "--workers", "2", "--threads", "4", "--timeout", "120", \
     "--bind", "0.0.0.0:8000", "--access-logfile", "-", "run:app"]
