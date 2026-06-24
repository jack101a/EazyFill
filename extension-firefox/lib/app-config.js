export const DEFAULT_API_BASE_URL = "https://eazyfill.tata-ocs.duckdns.org";

const SUPPORTED_AUTH_EMAIL_DOMAINS = new Set([
  "gmail.com", "googlemail.com", "hotmail.com", "outlook.com", "live.com", "msn.com",
  "proton.me", "protonmail.com", "pm.me", "rediffmail.com", "rediff.com", "yahoo.com",
  "ymail.com", "rocketmail.com", "icloud.com", "me.com", "mac.com", "aol.com",
  "zoho.com", "zohomail.com", "fastmail.com", "hey.com", "mail.com", "gmx.com",
  "gmx.net", "tutanota.com", "tuta.io"
]);

const BLOCKED_AUTH_EMAIL_DOMAINS = new Set([
  "10minutemail.com", "20minutemail.com", "anonaddy.com", "dispostable.com",
  "emailondeck.com", "fakeinbox.com", "getnada.com", "guerrillamail.com", "grr.la",
  "maildrop.cc", "mailinator.com", "mintemail.com", "moakt.com", "mytemp.email",
  "sharklasers.com", "temp-mail.org", "tempmail.com", "throwawaymail.com",
  "trashmail.com", "yopmail.com"
]);

export function normalizeAuthEmail(value) {
  return String(value || "").trim().toLowerCase();
}

export function authEmailValidationMessage(value) {
  const email = normalizeAuthEmail(value);
  const atIndex = email.lastIndexOf("@");
  const domain = atIndex > 0 && atIndex < email.length - 1
    ? email.slice(atIndex + 1).replace(/\.+$/, "")
    : "";
  if (!domain) return "Enter a valid email address.";
  if (BLOCKED_AUTH_EMAIL_DOMAINS.has(domain)) return "Temporary email addresses are not supported.";
  if (!SUPPORTED_AUTH_EMAIL_DOMAINS.has(domain)) {
    return "Use Gmail, Outlook, Hotmail, Proton Mail, Rediffmail, Yahoo, iCloud, Zoho, Fastmail, or another supported provider.";
  }
  return "";
}
