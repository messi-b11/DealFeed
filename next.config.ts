import type { NextConfig } from "next";
const developmentApi = process.env.NODE_ENV === "development" && process.env.DEALFEED_API_ORIGIN;
const config: NextConfig = {
  output: "export",
  images: { unoptimized: true },
  trailingSlash: true,
  ...(developmentApi ? { rewrites: async () => [{ source: "/api/:path*", destination: `${developmentApi}/:path*` }] } : {}),
};
export default config;
