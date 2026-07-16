# frontend — build with Vite, serve with nginx
# NOTE: build context is the REPO ROOT (workspace package @wavedesk/api-client
# lives outside frontend/): docker build -f frontend/Dockerfile .
FROM node:20-alpine AS build
WORKDIR /app
COPY packages/api-client ./packages/api-client
COPY frontend/package.json frontend/package-lock.json ./frontend/
WORKDIR /app/frontend
RUN npm ci
COPY frontend ./
RUN npm run build

FROM nginx:1.27-alpine
# Template rendered by the nginx image's envsubst at start — BACKEND_ORIGIN
# points at the Frappe http tier (CapRover internal hostname by default).
COPY frontend/deploy/default.conf.template /etc/nginx/templates/default.conf.template
ENV BACKEND_ORIGIN=http://srv-captain--wavedesk-http:8080
COPY --from=build /app/frontend/dist /usr/share/nginx/html
EXPOSE 80
