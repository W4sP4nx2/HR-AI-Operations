/** @type {import('next').NextConfig} */
// STATIC_EXPORT=1 → emit a fully static `out/` (Render Static Site: always-on,
// CDN, no free-tier cold start). Otherwise keep the standalone server bundle the
// Docker image / docker-compose use. The app is 100% client-side over an external
// API (no server actions/route handlers), so static export is safe.
const staticExport = process.env.STATIC_EXPORT === "1";

const nextConfig = {
  reactStrictMode: true,
  output: staticExport ? "export" : "standalone",
  ...(staticExport ? { images: { unoptimized: true } } : {}),
};

module.exports = nextConfig;
