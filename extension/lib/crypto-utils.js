export function bytesToBase64(bytes) {
  let binary = "";
  const chunkSize = 0x8000;
  for (let index = 0; index < bytes.length; index += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize));
  }
  return btoa(binary);
}

export function base64ToBytes(value) {
  const binary = atob(String(value || ""));
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

export function bytesToHex(bytes) {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function randomBase64(length) {
  const bytes = new Uint8Array(length);
  crypto.getRandomValues(bytes);
  return bytesToBase64(bytes);
}

async function deriveSyncKey({ sessionToken, legacyApiKey, syncSecret, deviceId, salt, scope = "user", secretMaterial = "" }) {
  const userMaterial = String(secretMaterial || syncSecret || "");
  const deviceMaterial = `${legacyApiKey || sessionToken || ""}\n${deviceId || ""}`;
  if (scope !== "device" && !userMaterial) {
    throw new Error("Sync secret is required");
  }
  const material = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(scope === "device" ? deviceMaterial : userMaterial),
    "HKDF",
    false,
    ["deriveKey"]
  );
  return crypto.subtle.deriveKey(
    {
      name: "HKDF",
      salt: base64ToBytes(salt),
      info: new TextEncoder().encode(scope === "device" ? "eazyfill sync blob v1" : "eazyfill sync blob v2 user"),
      hash: "SHA-256"
    },
    material,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"]
  );
}

export async function encryptSyncPayload(payload, { sessionToken, syncSecret, deviceId }) {
  if (!String(syncSecret || "").trim()) {
    throw new Error("Sync secret is required");
  }
  const salt = randomBase64(16);
  const ivBytes = new Uint8Array(12);
  crypto.getRandomValues(ivBytes);
  const key = await deriveSyncKey({ sessionToken, syncSecret, deviceId, salt, scope: "user" });
  const plaintext = new TextEncoder().encode(JSON.stringify(payload));
  const ciphertext = await crypto.subtle.encrypt({ name: "AES-GCM", iv: ivBytes }, key, plaintext);
  return {
    v: 2,
    alg: "AES-GCM-HKDF-SHA256-USER",
    salt,
    iv: bytesToBase64(ivBytes),
    ciphertext: bytesToBase64(new Uint8Array(ciphertext))
  };
}

function uniqueMaterials(values) {
  return Array.from(new Set(values.map((value) => String(value || "")).filter(Boolean)));
}

export async function decryptSyncPayload(envelope, { sessionToken, legacyApiKey, syncSecret, deviceId }) {
  if (!envelope || !envelope.salt || !envelope.iv || !envelope.ciphertext) {
    throw new Error("Unsupported sync blob");
  }
  const candidates = [];
  if (envelope.v === 2 && envelope.alg === "AES-GCM-HKDF-SHA256-USER") {
    for (const material of uniqueMaterials([syncSecret, legacyApiKey])) {
      candidates.push({ scope: "user", secretMaterial: material });
    }
  } else if (envelope.v === 1 && envelope.alg === "AES-GCM-HKDF-SHA256") {
    for (const material of uniqueMaterials([syncSecret, legacyApiKey])) {
      candidates.push({ scope: "user", secretMaterial: material });
    }
    candidates.push({ scope: "device", secretMaterial: "" });
  } else {
    throw new Error("Unsupported sync blob");
  }

  let lastError = null;
  for (const candidate of candidates) {
    try {
      const key = await deriveSyncKey({
        sessionToken,
        legacyApiKey,
        syncSecret,
        deviceId,
        salt: envelope.salt,
        scope: candidate.scope,
        secretMaterial: candidate.secretMaterial
      });
      const plaintext = await crypto.subtle.decrypt(
        { name: "AES-GCM", iv: base64ToBytes(envelope.iv) },
        key,
        base64ToBytes(envelope.ciphertext)
      );
      return JSON.parse(new TextDecoder().decode(plaintext));
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError || new Error("Sync blob decrypt failed");
}

export async function sha256Base64Payload(base64Value) {
  const bytes = base64ToBytes(base64Value);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return `sha256:${bytesToHex(new Uint8Array(digest))}`;
}

export function jsonToBase64(value) {
  return bytesToBase64(new TextEncoder().encode(JSON.stringify(value)));
}

export function jsonFromBase64(value) {
  return JSON.parse(new TextDecoder().decode(base64ToBytes(value)));
}
