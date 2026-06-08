/** @type {import('next').NextConfig} */
const nextConfig = {
  // Enable React Strict Mode for development best practices
  reactStrictMode: true,

  // Optimize for Vercel Edge Network deployment
  output: "standalone",

  // Image optimization configuration
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "*.hf.space",
      },
      {
        protocol: "https",
        hostname: "*.huggingface.co",
      },
    ],
    // Disable default image optimization for MJPEG streams
    unoptimized: true,
  },

  // Environment variables exposed to the browser
  env: {
    NEXT_PUBLIC_BACKEND_URL:
      process.env.NEXT_PUBLIC_BACKEND_URL ||
      "https://alex-universe11-bootcamp-ubsi-kai.hf.space",
  },

  // CRITICAL FIX 10: Cross-Origin Unblocking & Cache Busting
  // Blok async headers() dihapus sepenuhnya untuk mengizinkan stream MJPEG (multipart/x-mixed-replace) dari Hugging Face

  // Webpack configuration for client-side optimization
  webpack: (config, { isServer }) => {
    if (!isServer) {
      config.resolve.fallback = {
        ...config.resolve.fallback,
        fs: false,
        net: false,
        tls: false,
      };
    }
    return config;
  },
};

module.exports = nextConfig;
