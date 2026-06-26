ARG ALPINE_MIRROR=https://mirrors.aliyun.com/alpine
ARG NPM_REGISTRY=https://registry.npmmirror.com

FROM node:20-alpine AS builder

ARG ALPINE_MIRROR
ARG NPM_REGISTRY
ENV NPM_CONFIG_REGISTRY=${NPM_REGISTRY}

WORKDIR /app

RUN sed -i "s|https://dl-cdn.alpinelinux.org/alpine|${ALPINE_MIRROR}|g" /etc/apk/repositories

COPY package*.json /app/
RUN npm ci --no-audit --no-fund

COPY . /app
RUN npm run build

FROM nginx:1.27-alpine

ARG ALPINE_MIRROR

WORKDIR /usr/share/nginx/html

RUN sed -i "s|https://dl-cdn.alpinelinux.org/alpine|${ALPINE_MIRROR}|g" /etc/apk/repositories

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY docker-entrypoint.sh /docker-entrypoint.d/30-rewrite-api-base.sh

RUN sed -i 's/\r$//' /docker-entrypoint.d/30-rewrite-api-base.sh \
    && chmod +x /docker-entrypoint.d/30-rewrite-api-base.sh

EXPOSE 80
