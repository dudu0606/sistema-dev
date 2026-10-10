FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 UPLOAD_DIR=/data/uploads
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
# OKD roda com UID aleatorio (grupo 0): ajusta permissoes
RUN mkdir -p /data/uploads && chgrp -R 0 /app /data && chmod -R g=u /app /data
USER 1001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
