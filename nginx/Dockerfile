FROM nginx:1.30-alpine

# envsubst template: only substitute our custom vars, not nginx $variables
COPY nginx.conf.template /etc/nginx/templates/nginx.conf.template
ENV NGINX_ENVSUBST_OUTPUT_DIR=/etc/nginx
ENV NGINX_ENVSUBST_FILTER=NGINX_CLIENT_MAX_BODY_SIZE|NGINX_ACCESS_LOG_READS

ENV NGINX_CLIENT_MAX_BODY_SIZE=100m
ENV NGINX_ACCESS_LOG_READS=0

COPY docker-entrypoint.d/05-data-group.sh /docker-entrypoint.d/05-data-group.sh

RUN mkdir -p /var/cache/nginx/thumb_cache /var/cache/nginx/auth_cache
