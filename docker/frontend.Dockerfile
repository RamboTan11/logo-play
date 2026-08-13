FROM node:20-alpine AS build

WORKDIR /app/frontend

ARG VITE_PUBLIC_BASE_PATH=/generate-logo/
ARG VITE_API_BASE_URL=/generate-logo/api
ENV VITE_PUBLIC_BASE_PATH=${VITE_PUBLIC_BASE_PATH}
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend ./
RUN npm run build:real

FROM nginx:1.27-alpine

COPY --from=build /app/frontend/dist /usr/share/nginx/html
COPY docker/frontend.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
