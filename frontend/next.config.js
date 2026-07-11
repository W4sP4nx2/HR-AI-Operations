/** @type {import('next').NextConfig} */
// STATIC_EXPORT=1 → emit a fully static `out/` for a separately managed static
// host. Otherwise keep the standalone server bundle used by Docker Compose.
// The app is 100% client-side over an external API (no server actions/route
// handlers), so static export is safe.
const staticExport = process.env.STATIC_EXPORT === "1";

const nextConfig = {
  reactStrictMode: true,
  outputFileTracingRoot: __dirname,
  output: staticExport ? "export" : "standalone",
  ...(staticExport ? { images: { unoptimized: true } } : {}),
};

module.exports = nextConfig;
