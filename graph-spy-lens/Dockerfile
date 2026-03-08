# Stage 1: Build
FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .

# Pass API base URL at build time (e.g. http://backend:8000 for same-host backend)
ARG VITE_API_BASE=https://layertenbackend.sahilpatel.wiki
ENV VITE_API_BASE=${VITE_API_BASE}

RUN npm run build

# Stage 2: Serve with nginx
FROM nginx:alpine

# Copy built assets from builder
COPY --from=builder /app/dist /usr/share/nginx/html

# SPA routing (API is called to VITE_API_BASE from the client; for same-origin API use a reverse proxy or set VITE_API_BASE in build)
RUN echo 'server { \
    listen 80; \
    root /usr/share/nginx/html; \
    index index.html; \
    location / { try_files $uri $uri/ /index.html; } \
}' > /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
