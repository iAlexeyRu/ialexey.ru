export async function GET(context) {
  const siteUrl = context.site ? context.site.toString().replace(/\/$/, '') : 'https://ialexey.ru';
  const host = context.site ? context.site.host : 'ialexey.ru';

  const body = `User-agent: *
Allow: /
Disallow: /stats
Disallow: /stats/pageview

Sitemap: ${siteUrl}/sitemap-index.xml
Host: ${host}
`;

  return new Response(body, {
    headers: {
      'Content-Type': 'text/plain; charset=utf-8'
    }
  });
}
