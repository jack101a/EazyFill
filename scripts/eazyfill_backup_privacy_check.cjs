const fs = require("fs");
const os = require("os");
const path = require("path");

let chromium;
try {
  ({ chromium } = require("playwright"));
} catch (_) {
  ({ chromium } = require("playwright-core"));
}

const repoRoot = path.resolve(__dirname, "..");
const extensionPath = path.join(repoRoot, "extension");

function chromeExecutable() {
  const bundled = chromium.executablePath && chromium.executablePath();
  if (bundled && fs.existsSync(bundled)) return bundled;

  const msPlaywrightRoot = path.join(os.homedir(), "AppData", "Local", "ms-playwright");
  if (fs.existsSync(msPlaywrightRoot)) {
    const installed = fs.readdirSync(msPlaywrightRoot)
      .filter((name) => /^chromium-\d+$/.test(name))
      .sort()
      .reverse()
      .map((name) => path.join(msPlaywrightRoot, name, "chrome-win64", "chrome.exe"))
      .find((candidate) => fs.existsSync(candidate));
    if (installed) return installed;
  }

  for (const candidate of [
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe"
  ]) {
    if (fs.existsSync(candidate)) return candidate;
  }
  throw new Error("Chromium executable not found");
}

function sendRuntime(page, message) {
  return page.evaluate((payload) => new Promise((resolve) => chrome.runtime.sendMessage(payload, resolve)), message);
}

(async () => {
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), "eazyfill-backup-check-"));
  const downloadsPath = fs.mkdtempSync(path.join(os.tmpdir(), "eazyfill-downloads-"));
  const context = await chromium.launchPersistentContext(userDataDir, {
    executablePath: chromeExecutable(),
    headless: false,
    acceptDownloads: true,
    downloadsPath,
    args: [
      `--disable-extensions-except=${extensionPath}`,
      `--load-extension=${extensionPath}`
    ]
  });

  try {
    const worker = context.serviceWorkers()[0] || await context.waitForEvent("serviceworker", { timeout: 15000 });
    const extensionId = new URL(worker.url()).host;
    const page = await context.newPage();
    await page.goto(`chrome-extension://${extensionId}/options/options.html`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector("#overview-panel.active");

    await sendRuntime(page, {
      type: "SET_EXTENSION_STORAGE",
      values: {
        fp_settings: { extensionEnabled: true, theme: "dark" },
        fp_rules: [{
          id: "rule_secret",
          name: "Secret Rule",
          site: { pattern: "secret.example" },
          steps: [{ selector: { primary: "#secret" }, value: "secret-value" }],
          enabled: true
        }],
        fp_scripts: [{
          id: "script_secret",
          name: "Secret Script",
          rawCode: "// ==UserScript==\n// @name Secret Script\n// ==/UserScript==\nconsole.log(\"secret-code\")",
          parsedMeta: { matches: ["https://secret.example/*"] },
          enabled: true
        }]
      }
    });

    await page.reload({ waitUntil: "domcontentloaded" });
    await page.click('[data-panel="rules-panel"]');
    const rulesText = await page.locator("#rules-panel").innerText();
    await page.click('[data-panel="scripts-panel"]');
    const scriptsText = await page.locator("#scripts-panel").innerText();
    if (!/Secret Rule/.test(rulesText) || !/secret\.example/.test(rulesText)) {
      throw new Error(`Rule metadata was not visible: ${rulesText}`);
    }
    if (/secret-value/.test(rulesText)) {
      throw new Error(`Rule sensitive details leaked: ${rulesText}`);
    }
    if (!/Secret Script/.test(scriptsText) || !/secret\.example/.test(scriptsText)) {
      throw new Error(`Script metadata was not visible: ${scriptsText}`);
    }
    if (/secret-code/.test(scriptsText)) {
      throw new Error(`Script code leaked: ${scriptsText}`);
    }

    await page.click('[data-panel="sync-panel"]');
    const downloadPromise = page.waitForEvent("download");
    await page.click("#backup-export-btn");
    const download = await downloadPromise;
    const savePath = path.join(downloadsPath, download.suggestedFilename());
    await download.saveAs(savePath);
    const backupText = fs.readFileSync(savePath, "utf8");

    if (!backupText.startsWith("EAZYFILL_EXTENSION_BACKUP\n")) {
      throw new Error("Backup missing EazyFill marker");
    }
    if (/Secret Rule|Secret Script|secret-value|secret-code|secret\.example/.test(backupText)) {
      throw new Error("Encrypted backup leaked plaintext data");
    }

    await sendRuntime(page, { type: "SET_EXTENSION_STORAGE", values: { fp_rules: [], fp_scripts: [] } });
    const chooserPromise = page.waitForEvent("filechooser");
    await page.click("#backup-restore-btn");
    const chooser = await chooserPromise;
    await chooser.setFiles(savePath);
    await page.waitForFunction(() => /Backup restored/i.test(document.querySelector("#toast")?.textContent || ""), null, { timeout: 10000 });

    const restored = await sendRuntime(page, { type: "GET_EXTENSION_STORAGE", keys: ["fp_rules", "fp_scripts"] });
    const rule = restored.data?.fp_rules?.find((item) => item.id === "rule_secret");
    const script = restored.data?.fp_scripts?.find((item) => item.id === "script_secret");
    if (!rule || !script) {
      throw new Error(`Restore did not recover protected data: ${JSON.stringify(restored)}`);
    }

    console.log(JSON.stringify({
      ok: true,
      extensionId,
      backupFile: download.suggestedFilename(),
      encryptedBytes: backupText.length,
      restored: {
        rules: restored.data.fp_rules.length,
        scripts: restored.data.fp_scripts.length
      }
    }, null, 2));
  } finally {
    await context.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
