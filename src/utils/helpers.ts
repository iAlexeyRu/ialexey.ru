// Shared helper functions for ialexey.ru Astro website

export function cleanText(text: string): string {
  return (text || "").replace(/\n{3,}/g, "\n\n").trim();
}

export function compactText(text: string): string {
  return cleanText(text).replace(/\s+/g, " ").trim();
}

export function truncateText(value: string, limit: number): string {
  const text = compactText(value);
  if (text.length <= limit) {
    return text;
  }
  return text.slice(0, Math.max(0, limit - 1)).trimEnd() + "…";
}

export function removeLeadingEmoji(text: string): string {
  if (!text) return "";
  let cleaned = text.trim();
  
  // 1. Regional indicators (flags)
  const flagMatch = cleaned.match(/^(\p{RI}{2})\s*/u);
  if (flagMatch) {
    return cleaned.slice(flagMatch[1].length).trim();
  }
  
  // 2. Emojis with ZWJ and variant selectors
  const baseEmojiPart = `(?:[^\\s\\w\\d.,!?;:()""''«»а-яА-ЯёЁa-zA-Z][\\ufe00-\\ufe0f\\u20e3]?|[\\ud83c][\\udffb-\\udfff]?)`;
  const zwjRegex = new RegExp(`^(?:${baseEmojiPart}(?:\\u200d${baseEmojiPart})*)`, 'u');
  
  const match = cleaned.match(zwjRegex);
  if (match && match[0]) {
    const symbol = match[0];
    if (/\p{Emoji}/u.test(symbol) && !/^[#*0-9]$/.test(symbol[0])) {
      return cleaned.slice(symbol.length).trim();
    }
  }
  return cleaned;
}

export function getFirstSentence(text: string): string {
  if (!text) return "";
  const newlineIdx = text.indexOf('\n');
  const match = text.match(/^.*?[.!?](?:\s|\n|$)/s);
  if (match) {
    const sentence = match[0].trim();
    if (newlineIdx !== -1 && newlineIdx < match[0].length) {
      return text.slice(0, newlineIdx).trim();
    }
    return sentence;
  }
  if (newlineIdx !== -1) {
    return text.slice(0, newlineIdx).trim();
  }
  return text.trim();
}

export function formatDate(value: string): string {
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

export function formatDateRussian(value: string): string {
  if (!value) return "";
  try {
    const date = new Date(value);
    const formatter = new Intl.DateTimeFormat("ru-RU", {
      timeZone: "Europe/Moscow",
      day: "numeric",
      month: "long",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
    // Format: "25 мая 00:13" or "25 мая, 00:13"
    return formatter.format(date).replace(" в ", ", ");
  } catch (e) {
    return value;
  }
}

export function formatTimeOnly(value: string): string {
  if (!value) return "";
  try {
    const date = new Date(value);
    const formatter = new Intl.DateTimeFormat("ru-RU", {
      timeZone: "Europe/Moscow",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
    return formatter.format(date);
  } catch (e) {
    return "";
  }
}

export function getSmartBadge(text: string): { label: string; class: string; emoji: string } {
  const t = (text || "").toLowerCase();
  if (t.includes("слив") || t.includes("утек") || t.includes("секрет") || t.includes("leak") || t.includes("эксклюзив")) {
    return { label: "Сливы", class: "badge--leaks", emoji: "⚡" };
  }
  if (t.includes("gpt") || t.includes("gemini") || t.includes("claude") || t.includes("anthropic") || t.includes("openai") || t.includes("google") || t.includes("llama")) {
    return { label: "ИИ-Модели", class: "badge--ai", emoji: "🤖" };
  }
  if (t.includes("нейросеть") || t.includes("midjourney") || t.includes("sora") || t.includes("генераци") || t.includes("искусствен")) {
    return { label: "Нейросети", class: "badge--neural", emoji: "🎨" };
  }
  return { label: "Новости", class: "badge--news", emoji: "📰" };
}

export function getPostPath(item: any): string {
  if (!item) return "/";
  if (typeof item === 'object') {
    const messageId = item.message_id || item.id?.split(':').pop();
    return `/posts/${messageId}/`;
  }
  return `/posts/${item}/`;
}

export function formatViewsCount(views: number): string {
  if (!views) return "0";
  if (views >= 1000000) {
    return (views / 1000000).toFixed(1).replace('.0', '') + 'M';
  }
  if (views >= 1000) {
    return (views / 1000).toFixed(1).replace('.0', '') + 'K';
  }
  return views.toString();
}
