import { existsSync } from "node:fs";
import path from "node:path";
import type { NextConfig } from "next";

// The repository keeps a single .env at its root, shared with the backend and Compose, and
// Next only reads .env files from this directory. Variables already in the environment keep
// precedence (`APP_SURFACE=kiosk pnpm dev`, or Compose in the container), and the standalone
// image has no such file, so this only fills in what a dev server or local build lacks.
const rootEnvFile = path.resolve(__dirname, "..", ".env");
if (existsSync(rootEnvFile)) {
  process.loadEnvFile(rootEnvFile);
}

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
          { key: "Cross-Origin-Resource-Policy", value: "same-origin" },
          { key: "X-DNS-Prefetch-Control", value: "off" },
          { key: "X-Permitted-Cross-Domain-Policies", value: "none" },
          {
            key: "Permissions-Policy",
            value: "camera=(), geolocation=(), microphone=(self)",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
