/** @type {import('next').NextConfig} */
const nextConfig = {
  // Allow images from our local Python backend (port 8765) and the data folder served via /api/media
  images: {
    remotePatterns: [
      { protocol: "http", hostname: "localhost", port: "8765" },
      { protocol: "http", hostname: "127.0.0.1", port: "8765" },
    ],
  },
};

export default nextConfig;
