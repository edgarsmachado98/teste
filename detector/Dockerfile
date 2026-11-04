FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 ffmpeg \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt requirements-ultralytics.txt ./
# ULTRALYTICS=0 gera a imagem só com o motor ONNX (sem a dependência AGPL-3.0)
ARG ULTRALYTICS=1
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$ULTRALYTICS" = "1" ]; then pip install --no-cache-dir -r requirements-ultralytics.txt; fi
COPY vigia_detector ./vigia_detector
CMD ["python", "-m", "vigia_detector.main"]
