# Client websites renderer (website builder). Build context = repository root, because the site sections live in
# frontend/src/site-blocks and are shared with the HAIP editor:
#   docker compose -f docker-compose.prod.yml build sites
FROM node:20-alpine AS deps
WORKDIR /app/sites
COPY sites/package.json sites/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/sites/node_modules ./sites/node_modules
COPY sites ./sites
COPY frontend/src/site-blocks ./frontend/src/site-blocks
WORKDIR /app/sites
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3020 HOSTNAME=0.0.0.0
RUN addgroup -S nextjs && adduser -S nextjs -G nextjs
COPY --from=builder --chown=nextjs:nextjs /app/sites/.next/standalone ./
COPY --from=builder --chown=nextjs:nextjs /app/sites/.next/static ./.next/static
USER nextjs
EXPOSE 3020
CMD ["node", "server.js"]
