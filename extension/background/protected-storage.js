const PROTECTED_CACHE_PREFIX = "fp_protected:";
const PROTECTED_META_KEY = "fp_protected_meta";
const PROTECTED_CACHE_ALG = "AES-GCM-HKDF-SHA256";

const PROTECTED_FIXED_KEYS = new Set([
  "fp_auth",
  "fp_rules",
  "fp_scripts",
  "fp_profiles"
]);

const PROTECTED_DYNAMIC_PREFIXES = [
  "us_storage:",
  "us_require:",
  "us_resource:",
  "us_menu_commands:"
];

let protectedHydrationPromise = null;
let protectedCryptoKeyPromise = null;
let protectedMemoryCache = {};

function storageGet(keys) {
  return chrome.storage.local.get(keys);
}

function storageSet(values) {
  return chrome.storage.local.set(values);
}

function storageRemove(keys) {
  return chrome.storage.local.remove(keys);
}

function bytesToB64(bytes) {
  let binary = "";
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}

function b64ToBytes(value) {
  const binary = atob(String(value || ""));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

function randomB64(length) {
  const bytes = new Uint8Array(length);
  crypto.getRandomValues(bytes);
  return bytesToB64(bytes);
}

function protectedDiskKey(key) {
  return `${PROTECTED_CACHE_PREFIX}${key}`;
}

export function isProtectedStorageKey(key) {
  const name = String(key || "");
  return PROTECTED_FIXED_KEYS.has(name)
    || PROTECTED_DYNAMIC_PREFIXES.some((prefix) => name.startsWith(prefix));
}

async function getProtectedMeta() {
  const data = await storageGet([PROTECTED_META_KEY]);
  let meta = data[PROTECTED_META_KEY];
  if (!meta || meta.v !== 1 || !meta.salt || !meta.installId) {
    meta = {
      v: 1,
      alg: PROTECTED_CACHE_ALG,
      salt: randomB64(16),
      installId: crypto.randomUUID ? crypto.randomUUID() : randomB64(16),
      createdAt: Date.now()
    };
    await storageSet({ [PROTECTED_META_KEY]: meta });
  }
  return meta;
}

async function getProtectedCryptoKey() {
  if (protectedCryptoKeyPromise) return protectedCryptoKeyPromise;
  protectedCryptoKeyPromise = (async () => {
    const meta = await getProtectedMeta();
    const material = await crypto.subtle.importKey(
      "raw",
      new TextEncoder().encode(`${meta.installId}\n${chrome.runtime.id}`),
      "HKDF",
      false,
      ["deriveKey"]
    );
    return crypto.subtle.deriveKey(
      {
        name: "HKDF",
        salt: b64ToBytes(meta.salt),
        info: new TextEncoder().encode("eazyfill protected storage v1"),
        hash: "SHA-256"
      },
      material,
      { name: "AES-GCM", length: 256 },
      false,
      ["encrypt", "decrypt"]
    );
  })();
  try {
    return await protectedCryptoKeyPromise;
  } catch (error) {
    protectedCryptoKeyPromise = null;
    throw error;
  }
}

async function encryptProtectedValue(key, value) {
  const iv = new Uint8Array(12);
  crypto.getRandomValues(iv);
  const cryptoKey = await getProtectedCryptoKey();
  const plaintext = new TextEncoder().encode(JSON.stringify(value));
  const ciphertext = await crypto.subtle.encrypt(
    {
      name: "AES-GCM",
      iv,
      additionalData: new TextEncoder().encode(String(key))
    },
    cryptoKey,
    plaintext
  );
  return {
    v: 1,
    alg: PROTECTED_CACHE_ALG,
    iv: bytesToB64(iv),
    ciphertext: bytesToB64(new Uint8Array(ciphertext)),
    updatedAt: Date.now()
  };
}

async function decryptProtectedValue(key, envelope) {
  if (!envelope || envelope.v !== 1 || envelope.alg !== PROTECTED_CACHE_ALG || !envelope.iv || !envelope.ciphertext) {
    return undefined;
  }
  const cryptoKey = await getProtectedCryptoKey();
  const plaintext = await crypto.subtle.decrypt(
    {
      name: "AES-GCM",
      iv: b64ToBytes(envelope.iv),
      additionalData: new TextEncoder().encode(String(key))
    },
    cryptoKey,
    b64ToBytes(envelope.ciphertext)
  );
  return JSON.parse(new TextDecoder().decode(plaintext));
}

export async function hydrateProtectedCache() {
  if (protectedHydrationPromise) return protectedHydrationPromise;
  protectedHydrationPromise = (async () => {
    const allData = await storageGet(null);
    const nextCache = {};
    for (const [diskKey, envelope] of Object.entries(allData || {})) {
      if (!diskKey.startsWith(PROTECTED_CACHE_PREFIX)) continue;
      const key = diskKey.slice(PROTECTED_CACHE_PREFIX.length);
      try {
        const value = await decryptProtectedValue(key, envelope);
        if (value !== undefined) nextCache[key] = value;
      } catch (error) {
        console.warn("[EazyFill Protected Storage] Decrypt failed for key:", key, error.message || error);
      }
    }
    protectedMemoryCache = nextCache;
    return protectedMemoryCache;
  })();
  try {
    return await protectedHydrationPromise;
  } catch (error) {
    protectedHydrationPromise = null;
    throw error;
  }
}

export async function setProtectedValues(values = {}) {
  await hydrateProtectedCache();
  const encrypted = {};
  const plaintextKeys = [];
  for (const [key, value] of Object.entries(values)) {
    if (!isProtectedStorageKey(key)) continue;
    protectedMemoryCache[key] = value;
    encrypted[protectedDiskKey(key)] = await encryptProtectedValue(key, value);
    plaintextKeys.push(key);
  }
  if (Object.keys(encrypted).length) await storageSet(encrypted);
  if (plaintextKeys.length) await storageRemove(plaintextKeys);
}

export async function getProtectedValues(keys = []) {
  const cache = await hydrateProtectedCache();
  const requested = Array.isArray(keys) ? keys : [keys];
  const result = {};
  for (const key of requested) {
    if (isProtectedStorageKey(key) && cache[key] !== undefined) {
      result[key] = cache[key];
    }
  }
  return result;
}

export async function removeProtectedValues(keys = []) {
  const requested = Array.isArray(keys) ? keys : [keys];
  await hydrateProtectedCache();
  const diskKeys = [];
  for (const key of requested) {
    delete protectedMemoryCache[key];
    diskKeys.push(protectedDiskKey(key), key);
  }
  if (diskKeys.length) await storageRemove(diskKeys);
}

export async function getExtensionStorage(keys = []) {
  const requested = Array.isArray(keys) ? keys : [keys];
  const protectedKeys = requested.filter(isProtectedStorageKey);
  const localKeys = requested.filter((key) => !isProtectedStorageKey(key));
  const [localData, protectedData] = await Promise.all([
    localKeys.length ? storageGet(localKeys) : Promise.resolve({}),
    protectedKeys.length ? getProtectedValues(protectedKeys) : Promise.resolve({})
  ]);
  return { ...localData, ...protectedData };
}

export async function setExtensionStorage(values = {}) {
  const localValues = {};
  const protectedValues = {};
  for (const [key, value] of Object.entries(values || {})) {
    if (isProtectedStorageKey(key)) protectedValues[key] = value;
    else localValues[key] = value;
  }
  await Promise.all([
    Object.keys(localValues).length ? storageSet(localValues) : Promise.resolve(),
    Object.keys(protectedValues).length ? setProtectedValues(protectedValues) : Promise.resolve()
  ]);
}

export function resetProtectedStorageMemo() {
  protectedHydrationPromise = null;
  protectedCryptoKeyPromise = null;
  protectedMemoryCache = {};
}

export async function factoryResetLocalExtensionStorage() {
  resetProtectedStorageMemo();
  await Promise.all([
    chrome.storage.local.clear(),
    chrome.storage.session?.clear ? chrome.storage.session.clear() : Promise.resolve()
  ]);
  resetProtectedStorageMemo();
}
