# L'app bot : Next.js, front et runtime CopilotKit dans le même service.
#
# Sortie `standalone` : Next assemble un serveur avec les seules dépendances
# qu'il utilise réellement, ce qui évite d'embarquer `node_modules` en entier —
# quelques dizaines de mégaoctets au lieu de plusieurs centaines.

FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci


FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules node_modules
COPY . .
# Aucune clé au build : elles sont lues à l'exécution, dans la route API.
RUN npm run build


FROM node:22-alpine
WORKDIR /app

ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# `standalone` embarque déjà son propre `node_modules` réduit ; `static` et
# `public` restent servis depuis le disque.
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public

USER node
EXPOSE 3000
CMD ["node", "server.js"]
