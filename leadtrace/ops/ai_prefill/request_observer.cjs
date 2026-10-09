// Safe metadata only. Never write messages, headers, images, tokens or reasoning.
const fs = require('node:fs');
const path = require('node:path');
const original = globalThis.fetch;
globalThis.fetch = async function(input, init) {
  try {
    const url = new URL(typeof input === 'string' ? input : input.url);
    if (url.pathname.endsWith('/chat/completions') && typeof init?.body === 'string') {
      const body = JSON.parse(init.body);
      fs.appendFileSync(path.join(process.cwd(), 'runtime-requests.jsonl'), JSON.stringify({
        model: body.model ?? null, reasoning_effort: body.reasoning_effort ?? null,
        thinking: body.thinking?.type ?? null, max_tokens: body.max_tokens ?? null
      }) + '\n', {mode: 0o600});
    }
  } catch { /* Missing metadata must remain unverified. */ }
  return original.apply(this, arguments);
};
