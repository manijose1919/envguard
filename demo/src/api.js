const stripe = require("stripe")(process.env.STRIPE_SECRET_KEY);

const {
  DATABASE_URL,
  REDIS_URL: redisConn,
  LOG_LEVEL = "info",
} = process.env;

async function handleWebhook(req) {
  const secret = process.env.STRIPE_WEBHOOK_SECRET; // never added to .env.example!
  return stripe.webhooks.constructEvent(req.body, req.sig, secret);
}

module.exports = { handleWebhook, DATABASE_URL, redisConn, LOG_LEVEL };
