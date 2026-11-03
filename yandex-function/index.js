/* Yandex Cloud Function: validates contact-form submissions and sends them by Yandex SMTP.
   Required environment variables: SMTP_USER, SMTP_PASS; optional TO_EMAIL.
   Deploy with the nodemailer dependency from package.json.
*/

const nodemailer = require('nodemailer');

const SERVICE_LABELS = {
  'seller-protection': 'Защита продавцов маркетплейсов',
  'blocking-defense': 'Защита от блокировок и обвинений',
  'payout-delay': 'Задержка выплат',
  litigation: 'Претензионная и судебная работа',
  'patent-troll': 'Защита от патентных троллей',
  'trademark-defense': 'Защита товарных знаков',
  copyright: 'Защита авторских прав',
  'trademark-registration': 'Регистрация товарного знака',
  license: 'Лицензионный договор / концессия',
  consultation: 'Первичная консультация',
  other: 'Другое',
};

const ALLOWED_ORIGINS = [
  'https://ip-zashita.ru',
  'https://zegizegic-star.github.io',
];

function getRequestOrigin(event) {
  const headers = event.headers || {};
  return headers.origin || headers.Origin || '';
}

function corsHeaders(origin) {
  const headers = {
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Vary': 'Origin',
  };
  if (ALLOWED_ORIGINS.includes(origin)) {
    headers['Access-Control-Allow-Origin'] = origin;
  }
  return headers;
}

function json(statusCode, body, headers) {
  return {
    statusCode,
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  };
}

let transporter;
function getTransporter() {
  if (!transporter) {
    if (!process.env.SMTP_USER || !process.env.SMTP_PASS) {
      throw new Error('SMTP configuration is missing');
    }
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
  const origin = getRequestOrigin(event);
  const headers = corsHeaders(origin);

  if (origin && !ALLOWED_ORIGINS.includes(origin)) {
    return json(403, { error: 'Origin not allowed' }, headers);
  }
  if (event.httpMethod === 'OPTIONS') {
    return { statusCode: 204, headers, body: '' };
  }
  if (event.httpMethod !== 'POST') {
    return json(405, { error: 'Method not allowed' }, headers);
  }

  let data;
  try {
    data = JSON.parse(event.body || '{}');
  } catch (e) {
    return json(400, { error: 'Invalid JSON' }, headers);
  }

  // Honeypot: silently accept bot submissions without sending email.
  if (data._honey) {
    return json(200, { ok: true }, headers);
  }

  const name = String(data.name || '').trim();
  const email = String(data.email || '').trim();
  const phone = String(data.phone || '').trim();
  const company = String(data.company || '').trim();
  const service = String(data.service || '').trim();
  const description = String(data.description || '').trim();
  const callback = data.callback === true;
  const consent = data.consent === true;

  const emailValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
  const phoneDigits = phone.replace(/\D/g, '');

  if (
    name.length < 2 || name.length > 100 ||
    email.length > 254 || !emailValid ||
    phone.length > 40 ||
    (phone && phoneDigits.length < 10) ||
    (callback && phoneDigits.length < 10) ||
    company.length > 150 ||
    !Object.prototype.hasOwnProperty.call(SERVICE_LABELS, service) ||
    description.length < 10 || description.length > 5000 ||
    !consent
  ) {
    return json(400, { error: 'Validation failed' }, headers);
  }

  const serviceLabel = SERVICE_LABELS[service];
  const lines = [`Имя: ${name}`, `Email: ${email}`];
  if (phone) lines.push(`Телефон: ${phone}`);
  if (callback) lines.push('Нужен срочный обратный звонок: да');
  if (company) lines.push(`Компания: ${company}`);
  lines.push(`Услуга: ${serviceLabel}`, '', 'Описание задачи:', description);

  try {
    await getTransporter().sendMail({
      from: process.env.SMTP_USER,
      to: process.env.TO_EMAIL || process.env.SMTP_USER,
      replyTo: email,
      subject: `${callback ? '[СРОЧНО] ' : ''}Новая заявка с сайта — ${serviceLabel}`,
      text: lines.join('\n'),
    });
  } catch (error) {
    console.error('Contact form email delivery failed:', error.message);
    return json(502, { error: 'Delivery failed' }, headers);
  }

  return json(200, { ok: true }, headers);
};
