FROM node:24.15.0-alpine AS build

WORKDIR /workspace/canvas-web

COPY canvas-web/package*.json ./
RUN npm ci

WORKDIR /workspace/user-web
COPY user-web/package*.json ./
RUN npm ci

COPY canvas-web /workspace/canvas-web
COPY user-web /workspace/user-web

ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

RUN npm run build

FROM nginx:1.27.5-alpine

COPY user-web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /workspace/user-web/dist /usr/share/nginx/html

# Static files copied from a restrictive checkout must be readable by Nginx workers.
RUN chmod -R a+rX /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
