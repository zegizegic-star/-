/* Yandex Cloud Function — receives the site's contact form (as JSON)
   and emails it via SMTP. Runs on servers physically in Russia,
   unlike the previous FormSubmit.co setup, so personal data is first
   recorded/processed in the RF as required by 152-FZ.

   Runtime: Node.js 18. Needs the "nodemailer" dependency — deploy the
   zip built alongside this file (index.js + package.json +
   node_modules), not just this file pasted into the console editor.

   Required environment variables (set in the function's config):
     SMTP_USER — the sending Yandex mailbox, e.g. name@yandex.ru
     SMTP_PASS — an app password for that mailbox (not the normal
                 account password — generate one in Yandex ID security
                 settings, "Пароли приложений")
     TO_EMAIL  — where submissions should land (defaults to SMTP_USER
                 if not set, so you can send and receive on the same
                 mailbox)

   Required setting: enable public HTTP access on the function/trigger
   so the browser can call it directly (no auth token needed).
*/

const nodemailer = require('nodemailer');

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

let transporter;
function getTransporter() {
  if (!transporter) {
    transporter = nodemailer.createTransport({
      host: 'smtp.yandex.ru',
      port: 465,
      secure: true,
      auth: {
        user: process.env.SMTP_USER,
        pass: process.env.SMTP_PASS,
      },
    });
  }
  return transporter;
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

  const serviceLabel = SERVICE_LABELS[service] || service;
  const lines = [`Имя: ${name}`, `Email: ${email}`];
  if (company) lines.push(`Компания: ${company}`);
  lines.push(`Услуга: ${serviceLabel}`, '', 'Описание задачи:', description);

  try {
    await getTransporter().sendMail({
      from: process.env.SMTP_USER,
      to: process.env.TO_EMAIL || process.env.SMTP_USER,
      replyTo: email,
      subject: `Новая заявка с сайта — ${serviceLabel}`,
      text: lines.join('\n'),
    });
  } catch (e) {
    return json(502, { error: 'Delivery failed' });
  }

  return json(200, { ok: true });
};
