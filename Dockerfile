FROM node:24-alpine AS build
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN npm install -g pnpm@11.25.0 && pnpm install --frozen-lockfile
COPY . .
ARG VITE_QHOME_URL
ENV VITE_QHOME_URL=$VITE_QHOME_URL
RUN pnpm run build

FROM node:22-alpine
WORKDIR /app
RUN npm install -g serve
COPY --from=build /app/dist ./dist
EXPOSE 3000
CMD ["serve", "-s", "dist", "-l", "3000"]
