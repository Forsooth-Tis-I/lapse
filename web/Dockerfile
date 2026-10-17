# syntax=docker/dockerfile:1
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html tsconfig*.json vite.config.* ./
COPY src ./src
ENV VITE_USE_MOCK=false VITE_API_URL=/
RUN npm run build

FROM nginx:1.28-alpine
COPY --from=build /app/dist /usr/share/nginx/html
RUN printf '%s\n' \
    'server {' \
    '    listen 8080;' \
    '    root /usr/share/nginx/html;' \
    '    index index.html;' \
    '    location /api/ {' \
    '        proxy_pass http://api:8000;' \
    '        proxy_http_version 1.1;' \
    '        proxy_set_header Host $host;' \
    '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;' \
    '        proxy_set_header X-Forwarded-Proto $scheme;' \
    '        proxy_set_header Connection "";' \
    '        proxy_buffering off;' \
    '        proxy_cache off;' \
    '        proxy_read_timeout 3600s;' \
    '    }' \
    '    location / {' \
    '        try_files $uri $uri/ /index.html;' \
    '    }' \
    '}' \
    > /etc/nginx/conf.d/default.conf
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD wget -q -O /dev/null http://127.0.0.1:8080/ || exit 1
