#!/usr/bin/env node
/**
 * C5 (perf/auth plan, Workstream C): derive the app's build identifier once
 * per build instead of hand-editing sw.js's cache-version string on every
 * deploy. Prior to this, "haip-shell-v4" -> "v5" -> "v6" bumps were manual,
 * easy to forget, and the actual root cause of this session's repeated
 * "why isn't my change showing up" service-worker cache debugging.
 *
 * Runs as the `prebuild` npm lifecycle script (see package.json), so it
 * always executes before `next build`.
 *
 * Writes two things from the same single value:
 *   1. public/build-id.json  -- polled by the client (C1/C2) to detect a
 *      new deploy even on builds where sw.js's own bytes didn't change
 *      (defense in depth alongside the SW's own updatefound detection).
 *   2. public/sw.js           -- generated from sw.template.js with the
 *      __BUILD_ID__ placeholder in CACHE_NAME/STATIC_CACHE_NAME replaced,
 *      so the service worker's cache names change on every real deploy
 *      automatically, which is what actually makes the browser's
 *      byte-diff update check reliably fire.
 *
 * public/sw.js is generated + gitignored, NOT hand-edited -- the source of
 * truth is sw.template.js (outside public/, so this script never mutates a
 * git-tracked file with a baked-in build id, which would silently break
 * on every subsequent build since the placeholder would already be gone).
 */
const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

function computeBuildId() {
  try {
    return execSync("git rev-parse --short=12 HEAD", { cwd: __dirname, stdio: ["ignore", "pipe", "ignore"] })
      .toString()
      .trim();
  } catch {
    // No git history in this deploy environment (e.g. a tarball/rsync
    // deploy without .git) -- fall back to a timestamp. Still unique per
    // build, just not traceable back to a specific commit.
    return `ts-${Date.now()}`;
  }
}

const buildId = computeBuildId();
const rootDir = path.join(__dirname, "..");
const publicDir = path.join(rootDir, "public");

// 1. build-id.json
fs.writeFileSync(
  path.join(publicDir, "build-id.json"),
  JSON.stringify({ version: buildId, built_at: new Date().toISOString() }, null, 2) + "\n"
);

// 2. Generate public/sw.js from sw.template.js -- never read/write the same
// file, so there's no risk of the placeholder being consumed and gone by
// the next build.
const templatePath = path.join(rootDir, "sw.template.js");
const swPath = path.join(publicDir, "sw.js");
const template = fs.readFileSync(templatePath, "utf8");
if (!template.includes("__BUILD_ID__")) {
  console.error("[set-build-id] sw.template.js has no __BUILD_ID__ placeholder -- cache name won't be versioned this build.");
} else {
  fs.writeFileSync(swPath, template.split("__BUILD_ID__").join(buildId));
}

console.log(`[set-build-id] build id: ${buildId}`);
