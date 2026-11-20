/** Static export so the app can be hosted on Firebase Hosting (public dir = out). */
const nextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  reactStrictMode: true,
  // optional separate build folder (used for local test builds that must not touch `next dev`)
  ...(process.env.NEXT_DIST_DIR ? { distDir: process.env.NEXT_DIST_DIR } : {}),
};
export default nextConfig;
