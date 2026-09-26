function safeExternalUrl(value) {
  if (typeof value !== 'string' || value.length > 2048 || value.trim() !== value || value.includes('\\')) return null;
  try {
    const parsed = new URL(value);
    if (!['http:', 'https:'].includes(parsed.protocol) || !parsed.hostname || parsed.username || parsed.password) return null;
    return parsed.href;
  } catch (_) {
    return null;
  }
}

module.exports = { safeExternalUrl };
