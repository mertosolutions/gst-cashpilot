# FastAPI backend for Cloud Run (the web app calls it with the Firebase ID token).
FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
ENV PORT=8080 AUTH_MODE=firebase AUTO_SEED=false
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
