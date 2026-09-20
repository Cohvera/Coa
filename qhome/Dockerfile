FROM python:3.12-slim
WORKDIR /service
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home qhome
COPY app ./app
RUN mkdir /data && chown qhome:qhome /data
USER qhome
ENV QHOME_DATA_DIR=/data
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
