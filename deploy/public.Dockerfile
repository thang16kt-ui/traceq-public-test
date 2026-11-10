# syntax=docker/dockerfile:1
FROM node:22.21.1-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend ./
RUN npm run build

FROM python:3.12.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock \
    && groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home app \
    && mkdir /data && chown app:app /data
COPY --chown=app:app . .
COPY --from=frontend --chown=app:app /build/dist ./frontend/dist
USER app
EXPOSE 8000
CMD ["python", "scripts/run_public.py"]
