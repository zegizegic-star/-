/* Yandex Cloud Function — receives the site's contact form (as JSON)
   and forwards it to Telegram via the Bot API. Runs on servers
   physically in Russia, unlike the previous FormSubmit.co setup, so
   personal data is first recorded/processed in the RF as required by
   152-FZ, before it reaches the lawyer via Telegram.

   Runtime: Node.js 18 (needs the global fetch() it ships with — no
   npm dependencies, so this single file can be pasted directly into
   the Yandex Cloud console editor).

   Required environment variables (set in the function's config):
     BOT_TOKEN — the Telegram bot token from @BotFather
     CHAT_ID   — the numeric chat id to send messages to

   Required setting: enable public HTTP access on the function/trigger
   so the browser can call it directly (no auth token needed).
*/

const SERVICE_LABELS = {
  'seller-protection': 'Защита продавцов маркетплейсов',
  'blocking-defense': 'Защита от блокировок и обвинений',
  litigation: 'Претензионная и судебная работа',
  'patent-troll': 'Защита от патентных троллей',
  'trademark-defense': 'Защита товарных знаков',
  copyright: 'Защита авторских прав',
  'trademark-registration': 'Регистрация товарного знака',
  license: 'Лицензионный договор / концессия',
  consultation: 'Первичная консультация',
  other: 'Другое',
};

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': 'https://ip-zashita.ru',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

function json(statusCode, body) {
  return { statusCode, headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
}

module.exports.handler = async function (event) {
  if (event.httpMethod === 'OPTIONS') {
    return { statusCode: 204, headers: CORS_HEADERS, body: '' };
  }
  if (event.httpMethod !== 'POST') {
    return json(405, { error: 'Method not allowed' });
  }

  let data;
  try {
    data = JSON.parse(event.body || '{}');
  } catch (e) {
    return json(400, { error: 'Invalid JSON' });
  }

  // Honeypot field: real visitors never fill it in. If it's non-empty,
  // pretend success without sending anything.
  if (data._honey) {
    return json(200, { ok: true });
  }

  const name = String(data.name || '').trim();
  const email = String(data.email || '').trim();
  const company = String(data.company || '').trim();
  const service = String(data.service || '').trim();
  const description = String(data.description || '').trim();
  const consent = Boolean(data.consent);

  const emailValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
  if (!name || name.length < 2 || !emailValid || !service || description.length < 10 || !consent) {
    return json(400, { error: 'Validation failed' });
  }

  const lines = [
    '📩 Новая заявка с сайта ip-zashita.ru',
    `Имя: ${name}`,
    `Email: ${email}`,
  ];
  if (company) lines.push(`Компания: ${company}`);
  lines.push(`Услуга: ${SERVICE_LABELS[service] || service}`);
  lines.push(`Описание: ${description}`);

  const botToken = process.env.BOT_TOKEN;
  const chatId = process.env.CHAT_ID;

  const tgResponse = await fetch(`https://api.telegram.org/bot${botToken}/sendMessage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chat_id: chatId, text: lines.join('\n') }),
  });

  if (!tgResponse.ok) {
    return json(502, { error: 'Delivery failed' });
  }

  return json(200, { ok: true });
};
