#!/usr/bin/env node
// Factory Droid statusline — usage refresher (background worker).
//
// The status line shows Factory plan consumption (5-hour / weekly / monthly),
// but Droid's status-line payload does not carry those numbers and the billing
// limits API needs the CLI's credentials. That call takes a few hundred
// milliseconds — far too slow to run on every status-line tick.
//
// So it lives here instead: read the credentials, ask the API, write a tiny
// cache file that the status line renders. statusline.sh spawns this detached
// whenever the cache goes stale; statusline.ps1 does the same on Windows when
// node is available.
//
// Node's standard library only — no packages to install.
// Usage:  node fetch-usage.mjs
// Writes: ~/.factory/statusline-usage.json   (on success)
//         ~/.factory/statusline-usage.log    (on failure)
// Exit:   0 on success, 1 on any failure (the status line ignores this).

import { readFileSync, writeFileSync, renameSync, appendFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { createDecipheriv } from "node:crypto";

const FACTORY_DIR = process.env.FACTORY_HOME || join(homedir(), ".factory");
const CACHE_PATH = join(FACTORY_DIR, "statusline-usage.json");
const LOG_PATH = join(FACTORY_DIR, "statusline-usage.log");
const API_URL = process.env.FACTORY_API_BASE
  ? `${process.env.FACTORY_API_BASE.replace(/\/$/, "")}/api/billing/limits`
  : "https://api.factory.ai/api/billing/limits";
const TIMEOUT_MS = 8000;

function log(message) {
  try {
    appendFileSync(LOG_PATH, `${new Date().toISOString()} ${message}\n`);
  } catch {
    // A status line must never fail loudly.
  }
}

// Droid keeps credentials in one of three places, newest first:
//
//   auth.v2.keyring / auth.v2.loginkeychain  — OS keychain (macOS Keychain,
//                                              Windows Credential Manager,
//                                              libsecret on Linux)
//   auth.v2.file + auth.v2.key               — encrypted file, the portable
//                                              fallback
//   auth.json                                — plain JSON, oldest format
//
// The keychain is a moving target across platforms and would drag in a native
// dependency, so this worker reads the two file-based stores. If a machine
// holds its credentials in the keychain only, the usage segments stay hidden
// and the rest of the status line works normally.
function readAccessToken() {
  try {
    const key = Buffer.from(readFileSync(join(FACTORY_DIR, "auth.v2.key"), "utf8").trim(), "base64");
    const raw = readFileSync(join(FACTORY_DIR, "auth.v2.file"), "utf8").trim();

    // base64(iv) : base64(authTag) : base64(ciphertext), AES-256-GCM.
    const [iv, tag, data] = raw.split(":");
    if (!iv || !tag || !data) throw new Error("unexpected auth.v2.file format");

    const decipher = createDecipheriv("aes-256-gcm", key, Buffer.from(iv, "base64"));
    decipher.setAuthTag(Buffer.from(tag, "base64"));
    const plain = Buffer.concat([decipher.update(Buffer.from(data, "base64")), decipher.final()]);

    const credentials = JSON.parse(plain.toString("utf8"));
    if (credentials?.access_token) return credentials.access_token;
    throw new Error("decrypted credentials carry no access_token");
  } catch (error) {
    if (error?.code !== "ENOENT") {
      log(`auth.v2.file unusable (${error.message}); trying auth.json`);
    }
  }

  try {
    const credentials = JSON.parse(readFileSync(join(FACTORY_DIR, "auth.json"), "utf8"));
    if (credentials?.access_token) return credentials.access_token;
    log("auth.json carries no access_token");
  } catch (error) {
    if (error?.code !== "ENOENT") log(`auth.json unusable (${error.message})`);
  }

  return null;
}

// The API reports two pools. "standard" carries the plan's own limits; "core"
// stays empty unless the account is metered that way. Prefer whichever pool has
// a live window, so the numbers match what the Factory dashboard shows.
function pickPool(limits) {
  const pools = [limits?.standard, limits?.core].filter(Boolean);
  return pools.find((pool) => pool?.fiveHour?.windowEnd) ?? pools[0] ?? null;
}

function toEpochSeconds(value) {
  if (typeof value !== "string") return null;
  const ms = Date.parse(value);
  return Number.isNaN(ms) ? null : Math.floor(ms / 1000);
}

function windowOf(entry) {
  if (!entry || typeof entry.usedPercent !== "number") return null;
  return {
    usedPercent: entry.usedPercent,
    windowEnd: toEpochSeconds(entry.windowEnd),
  };
}

async function main() {
  const token = readAccessToken();
  if (!token) {
    log("no access token found; skipping refresh");
    process.exit(1);
  }

  const response = await fetch(API_URL, {
    headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });

  if (!response.ok) {
    log(`billing limits returned HTTP ${response.status}`);
    process.exit(1);
  }

  const pool = pickPool((await response.json())?.limits);
  if (!pool) {
    log("billing limits response had no usable pool");
    process.exit(1);
  }

  const cache = {
    fetched_at: Math.floor(Date.now() / 1000),
    fiveHour: windowOf(pool.fiveHour),
    weekly: windowOf(pool.weekly),
    monthly: windowOf(pool.monthly),
  };

  // Write to a temp file and rename, so a reader never sees a half-written cache.
  const tempPath = `${CACHE_PATH}.${process.pid}.tmp`;
  writeFileSync(tempPath, `${JSON.stringify(cache)}\n`);
  renameSync(tempPath, CACHE_PATH);
}

main().catch((error) => {
  log(`refresh failed: ${error.message}`);
  process.exit(1);
});
