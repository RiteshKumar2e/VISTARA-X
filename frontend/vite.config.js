import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

const PUBLIC_ROUTES = ['/', '/mission', '/architecture', '/technology', '/privacy', '/terms'];

// Writes sitemap.xml + a robots.txt Sitemap line, and a canonical link, only when
// the real public origin is configured. We never invent a domain.
function siteMetadata(siteUrl) {
  const origin = siteUrl.replace(/\/+$/, '');
  return {
    name: 'vistara-site-metadata',
    transformIndexHtml(html) {
      if (!origin) return html;
      return html.replace('</head>', `  <link rel="canonical" href="${origin}/" />\n  </head>`);
    },
    generateBundle() {
      if (!origin) return;
      const urls = PUBLIC_ROUTES.map((p) => `  <url><loc>${origin}${p}</loc></url>`).join('\n');
      this.emitFile({
        type: 'asset',
        fileName: 'sitemap.xml',
        source: `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`,
      });
      this.emitFile({
        type: 'asset',
        fileName: 'robots.txt',
        source: `User-agent: *\nAllow: /\n\nSitemap: ${origin}/sitemap.xml\n`,
      });
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_');
  return {
    plugins: [react(), siteMetadata(env.VITE_SITE_URL || '')],
    server: { port: 5173, strictPort: true },
    preview: { port: 4173 },
    // The lazily loaded 3D viewport (three.js) is ~590 kB raw / 150 kB gzip by design.
    build: { target: 'es2020', sourcemap: false, chunkSizeWarningLimit: 650 },
  };
});
