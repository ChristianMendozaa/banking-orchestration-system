import { fileURLToPath, URL } from "node:url"

import { defineConfig } from "vitest/config"

export default defineConfig({
  resolve: {
    alias: { "@": fileURLToPath(new URL(".", import.meta.url)) },
  },
  test: {
    environment: "node",
    include: ["tests/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      reporter: ["text", "json-summary"],
      include: ["lib/**/*.ts", "components/providers/**/*.tsx", "app/backend-api/**/*.ts"],
      exclude: ["lib/generated-api.ts"],
      thresholds: {
        statements: 35,
        branches: 21,
        functions: 52,
        lines: 35,
      },
    },
  },
})
