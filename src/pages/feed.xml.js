import rss from '@astrojs/rss';
import fs from 'node:fs';
import path from 'node:path';

export async function GET(context) {
  const dataDir = process.env.DATA_DIR || '/home/deploy/ialexey-feed/data';
  const prodFeedJsonPath = path.join(dataDir, 'feed.json');
  const localFeedJsonPath = path.resolve('src/data/feed.json');

  let parsedData = null;

  if (fs.existsSync(prodFeedJsonPath)) {
    try {
      parsedData = JSON.parse(fs.readFileSync(prodFeedJsonPath, 'utf-8'));
    } catch (e) {
      console.error(e);
    }
  }

  if (!parsedData && fs.existsSync(localFeedJsonPath)) {
    try {
      parsedData = JSON.parse(fs.readFileSync(localFeedJsonPath, 'utf-8'));
    } catch (e) {
      console.error(e);
    }
  }

  let feedItems = [];
  if (parsedData) {
    if (Array.isArray(parsedData)) {
      feedItems = parsedData;
    } else if (parsedData.items && Array.isArray(parsedData.items)) {
      feedItems = parsedData.items;
    }
  }

  // Sort by date descending
  const sortedItems = feedItems.sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());

  const channelUsername = "iAlexeyRu";
  
  // Title truncation helper
  function cleanText(text) {
    return (text || "").replace(/\n{3,}/g, "\n\n").trim();
  }
  function compactText(text) {
    return cleanText(text).replace(/\s+/g, " ").trim();
  }
  function truncateText(value, limit) {
    const text = compactText(value);
    if (text.length <= limit) {
      return text;
    }
    return text.slice(0, Math.max(0, limit - 1)).trimEnd() + "…";
  }

  return rss({
    title: 'Алексей Гетманец | Сливы и новости ИИ',
    description: 'Сливы и новости ИИ от Алексея Гетманца: короткая Telegram-лента, RSS и статические страницы постов.',
    site: context.site || 'https://ialexey.ru',
    items: sortedItems.map((item) => {
      const id = item.message_id || item.id.split(':').pop();
      const title = truncateText(item.text || "", 86) || `Пост Telegram ${id}`;
      return {
        title: title,
        pubDate: new Date(item.date),
        description: item.html || item.text,
        link: `/posts/${id}/`,
        customData: `<source url="${item.url || `https://t.me/${channelUsername}/${id}`}">${channelUsername}</source>`
      };
    }),
    customData: `<language>ru</language>`,
  });
}
