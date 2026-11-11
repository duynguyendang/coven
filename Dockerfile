# syntax=docker/dockerfile:1
# Coven Cloud: Node.js, no build step. The relay/CLI are Python and run on developer machines, not here.
FROM node:22-slim

ENV NODE_ENV=production \
    PORT=8080

WORKDIR /app

# Install production dependencies first so this layer caches. The AWS SDK is an optional
# dependency used only when COVEN_STORE=dynamo.
COPY server/package.json server/package-lock.json ./server/
RUN cd server && npm ci --omit=dev --no-audit --no-fund

COPY server/src ./server/src
COPY web ./web

USER node
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD node -e "fetch('http://127.0.0.1:'+process.env.PORT+'/healthz').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

WORKDIR /app/server
CMD ["node", "src/main.ts"]
