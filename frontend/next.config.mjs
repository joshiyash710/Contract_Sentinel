/** @type {import('next').NextConfig} */

// Server-only env (NOT NEXT_PUBLIC_*): the dev-proxy target for the feature-011 backend.
const API_ORIGIN = process.env.API_PROXY_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    // Dev (Q4 / spec EC-3): the browser calls same-origin /api/* and Next proxies to the
    // 011 backend, so no cross-origin request is made and 011's CORS allowlist (:5173) is
    // moot — with ZERO backend change. Prod uses a real reverse proxy.
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }];
  },
};

export default nextConfig;
