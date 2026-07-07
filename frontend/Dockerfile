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
COPY frontend/deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/frontend/dist /usr/share/nginx/html
EXPOSE 80
