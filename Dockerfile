# ── Frontend multi-stage Dockerfile ───────────────
# Stage 1: Build the React app
FROM node:20-alpine AS build

WORKDIR /app

# Install dependencies first (cache layer)
COPY package.json package-lock.json* ./
RUN npm ci

# Copy source files and vendor
COPY index.html tsconfig*.json vite.config.ts ./
COPY src/ src/
COPY public/ public/
COPY vendor/ vendor/

# Build for production
RUN npm run build

# Stage 2: Serve with Nginx
FROM nginx:alpine

# Remove default nginx config
RUN rm /etc/nginx/conf.d/default.conf

# Copy custom nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built frontend from build stage
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
