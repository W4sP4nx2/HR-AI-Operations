/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Emit a self-contained server bundle for a small production image.
  output: "standalone",
};

module.exports = nextConfig;
