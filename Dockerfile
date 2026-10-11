FROM node:22-bookworm-slim AS frontend
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY app ./app
COPY lib ./lib
COPY public ./public
COPY backend/catalog.json backend/service_categories.json ./backend/
COPY next.config.ts tsconfig.json postcss.config.mjs ./
ENV NEXT_PUBLIC_API_URL=/api
RUN npm run build

FROM python:3.13-slim
WORKDIR /app
COPY backend/requirements.lock.txt ./backend/requirements.lock.txt
RUN pip install --no-cache-dir -r backend/requirements.lock.txt
COPY backend ./backend
COPY scripts/serve_app.py ./scripts/serve_app.py
COPY --from=frontend /app/out ./out
RUN useradd --create-home --uid 10001 dealfeed && mkdir -p /data && chown dealfeed:dealfeed /data
USER dealfeed
ENV PORT=8080 DATABASE_PATH=/data/dealfeed.sqlite AI_MODE=live DEMO_AUTH_ENABLED=false ASYNC_ANALYSIS=true
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=4)"
CMD ["python", "-m", "scripts.serve_app"]
