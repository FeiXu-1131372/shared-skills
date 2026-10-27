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

import { readFileSync, writeFileSync, renameSync, appendFileSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { createDecipheriv } from "node:crypto";
import { spawnSync } from "node:child_process";

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
// The macOS Keychain and libsecret are a moving target and would drag in a
// native dependency, so on those platforms this worker reads the file-based
// stores only. If such a machine holds its credentials in the keychain only,
// the usage segments stay hidden and the rest of the status line works.
//
// Windows is the exception. Once Droid moves to auth.v2.keyring, auth.v2.file
// stops being rewritten and its token expires, so the billing call fails with
// HTTP 401 for good. auth.v2.keyring is the same AES-256-GCM format, encrypted
// with a key Droid keeps in Credential Manager; PowerShell ships with Windows
// and can read that key without adding a dependency. The keyring is only tried
// first when it is newer than auth.v2.file, so a machine whose file is still
// current never pays for the PowerShell hop.
const AUTH_FILE = join(FACTORY_DIR, "auth.v2.file");
const AUTH_KEYRING = join(FACTORY_DIR, "auth.v2.keyring");

function mtimeMs(path) {
  try {
    return statSync(path).mtimeMs;
  } catch {
    return -1;
  }
}

// base64(iv) : base64(authTag) : base64(ciphertext), AES-256-GCM.
function decryptCredentials(raw, key) {
  const [iv, tag, data] = raw.trim().split(":");
  if (!iv || !tag || !data) throw new Error("unexpected credential file format");

  const decipher = createDecipheriv("aes-256-gcm", key, Buffer.from(iv, "base64"));
  decipher.setAuthTag(Buffer.from(tag, "base64"));
  const plain = Buffer.concat([decipher.update(Buffer.from(data, "base64")), decipher.final()]);

  const credentials = JSON.parse(plain.toString("utf8"));
  if (!credentials?.access_token) throw new Error("decrypted credentials carry no access_token");
  return credentials.access_token;
}

// Droid's encryption key is the base64 text of a 32-byte key. It is read into
// memory only for the one decryption: PowerShell writes it to a pipe, and it
// never touches disk or the log.
const CRED_TARGET = "Factory CLI/auth-encryption-key";
const CRED_READ_SCRIPT = `
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices;
public static class CredReader {
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
  struct CREDENTIAL { public uint Flags; public uint Type; public string TargetName; public string Comment; public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten; public uint CredentialBlobSize; public IntPtr CredentialBlob; public uint Persist; public uint AttributeCount; public IntPtr Attributes; public string TargetAlias; public string UserName; }
  [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool CredRead(string target, uint type, uint flags, out IntPtr cred);
  [DllImport("advapi32.dll")] static extern void CredFree(IntPtr cred);
  public static byte[] Read(string target) {
    IntPtr p; if (!CredRead(target, 1, 0, out p)) return null;
    try { var c = (CREDENTIAL)Marshal.PtrToStructure(p, typeof(CREDENTIAL)); var b = new byte[c.CredentialBlobSize]; Marshal.Copy(c.CredentialBlob, b, 0, b.Length); return b; }
    finally { CredFree(p); }
  }
}
"@
$b = [CredReader]::Read('${CRED_TARGET}')
if ($null -eq $b) { exit 3 }
[Console]::Out.Write([Convert]::ToBase64String($b))
`;

function readWindowsKeyringKey() {
  // Windows PowerShell 5.1 (powershell.exe) starts about twice as fast as
  // pwsh 7 and is present on every Windows install.
  const result = spawnSync(
    "powershell.exe",
    [
      "-NoProfile",
      "-NonInteractive",
      "-ExecutionPolicy", "Bypass",
      "-EncodedCommand", Buffer.from(CRED_READ_SCRIPT, "utf16le").toString("base64"),
    ],
    { encoding: "utf8", windowsHide: true, timeout: 15000 },
  );
  if (result.status !== 0 || !result.stdout) {
    throw new Error(`could not read "${CRED_TARGET}" from Credential Manager (exit ${result.status})`);
  }

  const blob = Buffer.from(result.stdout, "base64");
  const key = blob.length === 32 ? blob : Buffer.from(blob.toString("utf8").trim(), "base64");
  if (key.length !== 32) throw new Error("Credential Manager key is not 32 bytes");
  return key;
}

function tokenFromKeyring() {
  try {
    return decryptCredentials(readFileSync(AUTH_KEYRING, "utf8"), readWindowsKeyringKey());
  } catch (error) {
    if (error?.code !== "ENOENT") log(`auth.v2.keyring unusable (${error.message})`);
    return null;
  }
}

function tokenFromEncryptedFile() {
  try {
    const key = Buffer.from(readFileSync(join(FACTORY_DIR, "auth.v2.key"), "utf8").trim(), "base64");
    return decryptCredentials(readFileSync(AUTH_FILE, "utf8"), key);
  } catch (error) {
    if (error?.code !== "ENOENT") log(`auth.v2.file unusable (${error.message})`);
    return null;
  }
}

function tokenFromPlainJson() {
  try {
    const credentials = JSON.parse(readFileSync(join(FACTORY_DIR, "auth.json"), "utf8"));
    if (credentials?.access_token) return credentials.access_token;
    log("auth.json carries no access_token");
  } catch (error) {
    if (error?.code !== "ENOENT") log(`auth.json unusable (${error.message})`);
  }
  return null;
}

function readAccessToken() {
  const sources = [tokenFromEncryptedFile, tokenFromPlainJson];
  if (process.platform === "win32") {
    const keyringIsNewer = mtimeMs(AUTH_KEYRING) > mtimeMs(AUTH_FILE);
    sources.splice(keyringIsNewer ? 0 : 1, 0, tokenFromKeyring);
  }

  for (const read of sources) {
    const token = read();
    if (token) return token;
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
