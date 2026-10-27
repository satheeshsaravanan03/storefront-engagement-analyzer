/** @type {import('next').NextConfig} */
const nextConfig = {
  // Strict mode causes double-mount which breaks video autoplay
  reactStrictMode: false,

  // Explicitly set video MIME type — fixes Windows dev server serving mp4 wrong
  async headers() {
    return [
      {
        source: '/:path*.mp4',
        headers: [
          { key: 'Content-Type',  value: 'video/mp4' },
          { key: 'Accept-Ranges', value: 'bytes'     },
          { key: 'Cache-Control', value: 'public, max-age=31536000' },
        ],
      },
      {
        source: '/:path*.avi',
        headers: [{ key: 'Content-Type', value: 'video/x-msvideo' }],
      },
    ];
  },

  env: {
    NEXT_PUBLIC_BACKEND_URL:
      process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000',
  },
};

module.exports = nextConfig;
