FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DOCKET_ENV=production
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin poppler-utils zbar-tools && rm -rf /var/lib/apt/lists/*
WORKDIR /service
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN python -m app.ocr.model_setup --destination /service/models
ENV TESSDATA_PREFIX=/service/models OMP_THREAD_LIMIT=1 OCR_MAX_CONCURRENT_DOCS=1
RUN python -c "import urllib.request; urllib.request.urlretrieve('https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem', '/service/rds-ca.pem')" && chmod 644 /service/rds-ca.pem
RUN useradd --uid 10001 --create-home docket
USER docket
EXPOSE 8000
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--no-access-log","--proxy-headers","--forwarded-allow-ips=*"]
