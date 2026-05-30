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

  const siteUrl = context.site ? context.site.toString().replace(/\/$/, '') : 'https://ialexey.ru';
  const siteAuthor = "Алексей Гетманец";
  const siteDescription = "Сливы и новости ИИ от Алексея Гетманца: короткая Telegram-лента, RSS и статические страницы постов.";
  const telegramUrl = "https://t.me/iAlexeyRu";
  const xProfileUrl = "https://x.com/iAlexeyRu";

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

  function formatDate(value) {
    if (!value) return "";
    try {
      const date = new Date(value);
      const formatter = new Intl.DateTimeFormat("ru-RU", {
        timeZone: "Europe/Moscow",
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      });
      return formatter.format(date).replace(",", "");
    } catch (e) {
      return value;
    }
  }

  const lines = [
    `# ${siteAuthor}`,
    "",
    `> ${siteDescription}`,
    "",
    "## Обо мне",
    "Я Алексей Гетманец, делюсь свежими новостями, сливами и инсайдами из мира искусственного интеллекта и нейросетей.",
    "",
    "## Контакты & Сообщества",
    `- Telegram-канал: ${telegramUrl}`,
    `- X / Twitter: ${xProfileUrl}`,
    `- RSS-лента: ${siteUrl}/feed.xml`,
    `- Карта сайта: ${siteUrl}/sitemap-index.xml`,
    `- Спецификация API (OpenAPI): ${siteUrl}/openapi.json`,
    `- Каталог API: ${siteUrl}/.well-known/api-catalog`,
    `- Навыки для ИИ-агентов: ${siteUrl}/.well-known/agent-skills/index.json`,
    "",
    "## Последние публикации в Telegram",
    "",
  ];

  if (sortedItems.length === 0) {
    lines.push("Постов пока нет.");
  } else {
    for (const item of sortedItems.slice(0, 10)) {
      const id = item.message_id || item.id.split(':').pop();
      const title = truncateText(item.text || "", 86) || `Пост Telegram ${id}`;
      const date = formatDate(item.date);
      const postUrl = `${siteUrl}/posts/${id}/`;
      lines.push(`### [${title}](${postUrl})`);
      lines.push(`*Опубликовано: ${date} MSK*`);
      lines.push("");
      lines.push(item.text || "");
      lines.push("");
      lines.push("---");
      lines.push("");
    }
  }

  const body = lines.join("\n") + "\n";

  return new Response(body, {
    headers: {
      'Content-Type': 'text/markdown; charset=utf-8'
    }
  });
}
