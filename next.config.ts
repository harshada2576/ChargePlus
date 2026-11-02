import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  outputFileTracingIncludes: {
    "/api/intelligence": ["./data/ml/**/*"],
  },
};

export default nextConfig;
