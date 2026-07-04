FROM python:3.13-slim

# libgomp1 is LightGBM's runtime OpenMP dependency — that's all this image needs.
# No build-essential/g++/cmdstan here: Prophet is deliberately excluded (see
# requirements-prod.txt) since the API/scheduler never import it, only the local-only
# backtest script does, and compiling Prophet's Stan backend from source is the kind of
# CPU/RAM-heavy step that has no business running on a small production box.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY backend/app ./app

EXPOSE 8000
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
