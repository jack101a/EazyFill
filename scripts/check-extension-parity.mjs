import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const chromeRoot = path.join(root, "extension");
const firefoxRoot = path.join(root, "extension-firefox");
const ignored = new Set(["manifest.json", "README.md"]);

function filesUnder(directory, prefix = "") {
  const files = [];
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const relative = path.join(prefix, entry.name);
    if (entry.isDirectory()) files.push(...filesUnder(path.join(directory, entry.name), relative));
    else if (!ignored.has(relative.replaceAll("\\", "/"))) files.push(relative);
  }
  return files;
}

const chromeFiles = filesUnder(chromeRoot);
const firefoxFiles = filesUnder(firefoxRoot);
assert.deepEqual(
  firefoxFiles.map((file) => file.replaceAll("\\", "/")).sort(),
  chromeFiles.map((file) => file.replaceAll("\\", "/")).sort(),
  "Chrome and Firefox extension file sets differ"
);

const mismatches = chromeFiles.filter((relative) => (
  !fs.readFileSync(path.join(chromeRoot, relative)).equals(fs.readFileSync(path.join(firefoxRoot, relative)))
));
assert.deepEqual(
  mismatches.map((file) => file.replaceAll("\\", "/")),
  [],
  "Shared Chrome and Firefox extension files differ"
);

console.log(`extension parity ok (${chromeFiles.length} shared files)`);
