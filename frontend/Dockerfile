FROM node:24-slim AS build
WORKDIR /web
COPY package*.json ./
RUN npm ci
COPY . .
ENV BACKEND_URL=http://api:8000
RUN npm run build
FROM node:24-slim
WORKDIR /web
ENV NODE_ENV=production BACKEND_URL=http://api:8000
COPY --from=build /web ./
USER node
EXPOSE 3000
CMD ["node","node_modules/next/dist/bin/next","start","--hostname","0.0.0.0"]
