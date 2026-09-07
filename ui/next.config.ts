import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Requis par `ui/Dockerfile` : Next assemble un serveur autonome avec les
  // seules dépendances qu'il utilise, au lieu d'exiger `node_modules` entier
  // dans l'image.
  output: "standalone",
};

export default nextConfig;
