FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p instance uploads outputs
ENV PYTHONUNBUFFERED=1
EXPOSE 5000
CMD ["gunicorn", "run:app", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "--timeout", "300"]
