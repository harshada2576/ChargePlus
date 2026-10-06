# ChargePlus production image (Phase 6.1).
# Reproducible Next.js runtime. Python ingestion/warehouse jobs run in
# GitHub Actions (see .github/workflows/scheduled_ingestion.yml), not here.
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Build-time public vars must be present (CI supplies dummy values; real
# values are provided at runtime via environment).
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
RUN addgroup -S app && adduser -S app -G app
COPY --from=builder /app/package.json /app/package-lock.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
USER app
EXPOSE 3000
CMD ["npm", "run", "start"]
