FROM nginx:1.27-alpine

# envsubst template: only substitute our custom vars, not nginx $variables
COPY nginx.conf.template /etc/nginx/templates/nginx.conf.template
ENV NGINX_ENVSUBST_OUTPUT_DIR=/etc/nginx
ENV NGINX_ENVSUBST_FILTER=NGINX_CLIENT_MAX_BODY_SIZE

ENV NGINX_CLIENT_MAX_BODY_SIZE=100m

RUN mkdir -p /var/cache/nginx/thumb_cache /var/cache/nginx/auth_cache
