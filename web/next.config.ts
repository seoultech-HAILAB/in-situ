import path from "node:path";
import type { NextConfig } from "next";
import { PHASE_DEVELOPMENT_SERVER } from "next/constants";

// Production build is a static export served by FastAPI. In development the
// Next dev server proxies /api to the running FastAPI backend.
export default function config(phase: string): NextConfig {
  const base: NextConfig = {
    // Shared, framework-free review logic lives in ../src (also used by tests).
    // Those modules must resolve this app's React, not the legacy app's copy.
    turbopack: {
      root: path.join(__dirname, ".."),
      resolveAlias: {
        react: "./node_modules/react",
        "react/jsx-runtime": "./node_modules/react/jsx-runtime.js",
        "react/jsx-dev-runtime": "./node_modules/react/jsx-dev-runtime.js",
      },
    },
  };
  if (phase === PHASE_DEVELOPMENT_SERVER) {
    const api = process.env.TRACE_API ?? "http://127.0.0.1:8000";
    return { ...base, rewrites: async () => [{ source: "/api/:path*", destination: `${api}/api/:path*` }] };
  }
  return { ...base, output: "export", images: { unoptimized: true } };
}
