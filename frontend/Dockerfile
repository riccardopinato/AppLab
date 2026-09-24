FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
ARG VITE_BACKEND_URL=http://localhost:8000
ARG VITE_GATEWAY_URI=localhost:8080
ENV VITE_BACKEND_URL=${VITE_BACKEND_URL}
ENV VITE_GATEWAY_URI=${VITE_GATEWAY_URI}
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
