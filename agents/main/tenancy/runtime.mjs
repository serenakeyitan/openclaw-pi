import fs from "node:fs";
import fsp from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";

export const TENANCY_ROOT = "/root/.openclaw/agents/main/tenancy";
export const USERS_ROOT = path.join(TENANCY_ROOT, "users");
export const GLOBAL_ROOT = path.join(TENANCY_ROOT, "global");
export const SERVERS_ROOT = path.join(TENANCY_ROOT, "servers");

const OPENCLAW_BOT_USER_ID = String(process.env.OPENCLAW_BOT_USER_ID ?? "").trim();
const CLAUDECODE_BOT_USER_ID = String(process.env.CLAUDECODE_BOT_USER_ID ?? process.env.CLOUDCODE_BOT_USER_ID ?? "").trim();

const MANAGED_CHANNELS_PATH = path.join(GLOBAL_ROOT, "managed_channels.json");
const POLICIES_PATH = path.join(GLOBAL_ROOT, "policies.md");

export const ADMIN_USER_ID = "878113709132771358";

const SYNC_EVERY_MS = 5 * 60 * 1000;
const RECENT_MSG_LIMIT = 100;
const SETUP_CODE_TTL_MS = 10 * 60 * 1000;

let started = false;
let syncTimer = null;
let discordApi = null;

let managedChannelsCache = null; // Array<{guild_id, channel_id}>
let policiesCache = null; // { allowNonAdminGlobalRead: boolean }

let protocolModPromise = null;
async function protocol() {
  // Shared protocol utilities live in /root/shared/protocol/.
  // Use a file:// import so this works outside of a Node package workspace.
  if (!protocolModPromise) protocolModPromise = import("file:///root/shared/protocol/index.mjs");
  return await protocolModPromise;
}

// Import sentinel: helps verify the gateway actually loaded this module.
try {
  fs.appendFileSync("/tmp/openclaw-tenancy-load.log", `${new Date().toISOString()} tenancy runtime imported\n`, { encoding: "utf8" });
} catch {
  // ignore
}

function isoNow() {
  return new Date().toISOString();
}

function tenancyDebug(line) {
  // Best-effort local debug log. Keep it redacted and never throw.
  try {
    const p = "/tmp/openclaw-tenancy-debug.log";
    const s = redactText(String(line ?? ""));
    fs.appendFileSync(p, s.endsWith("\n") ? s : `${s}\n`, { encoding: "utf8" });
  } catch {
    // ignore
  }
}

function isStringId(v) {
  return typeof v === "string" && /^\d+$/.test(v);
}

function safeParseJson(text) {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

async function readJsonFile(filePath) {
  const raw = await fsp.readFile(filePath, "utf8").catch(() => null);
  if (!raw) return null;
  return safeParseJson(raw);
}

async function writeJsonAtomic(filePath, obj) {
  const dir = path.dirname(filePath);
  await fsp.mkdir(dir, { recursive: true });
  const tmp = `${filePath}.tmp.${process.pid}.${Date.now()}`;
  const data = `${JSON.stringify(obj, null, 2)}\n`;
  await fsp.writeFile(tmp, data, { mode: 0o600 });
  try {
    await fsp.rename(tmp, filePath);
  } catch (err) {
    // Best-effort fallback: some environments occasionally throw ENOENT on rename
    // (e.g. transient fs issues). Prefer correctness over atomicity.
    await fsp.writeFile(filePath, data, { mode: 0o600 });
    await fsp.unlink(tmp).catch(() => {});
  }
}

function normalizeUserId(userId) {
  return typeof userId === "string" ? userId.trim() : "";
}

function allowlistPathForChannel(channelId) {
  return path.join(TENANCY_ROOT, `channel_${channelId}_allowlist.json`);
}

function userDir(userId) {
  return path.join(USERS_ROOT, userId);
}

function userFile(userId, name) {
  return path.join(userDir(userId), name);
}

function secretsDir(userId) {
  return path.join(userDir(userId), "secrets");
}

function providerKeyFileName(provider) {
  const p = String(provider ?? "").trim().toLowerCase();
  if (!p) return null;
  // Keep it predictable: <provider>_api_key
  return `${p}_api_key`;
}

function providerKeyPath(userId, provider) {
  const name = providerKeyFileName(provider);
  if (!name) return null;
  return path.join(secretsDir(userId), name);
}

function looksSensitivePath(p) {
  const s = String(p).toLowerCase();
  return (
    s.includes("/credentials") ||
    s.includes("/secrets") ||
    s.includes("/tokens") ||
    s.includes("/.env") ||
    s.includes(".key") ||
    /(^|\/)(key|keys)(\/|$)/.test(s) ||
    s.includes("apikey") ||
    s.includes("api_key") ||
    s.includes("private") ||
    s.includes("secret") ||
    s.includes("/root/.openclaw/credentials")
  );
}

// Conservative redaction: remove obvious tokens/keys from any output that could reach Discord.
export function redactText(input) {
  const text = String(input ?? "");
  if (!text) return text;

  let out = text;
  // querystring token=
  out = out.replace(/([?&]token=)[^\\s&#]+/gi, "$1REDACTED");
  // OpenAI style keys
  out = out.replace(/\bsk-[A-Za-z0-9_-]{10,}\b/g, "sk-REDACTED");
  // GitHub tokens
  out = out.replace(/\bgh[pousr]_[A-Za-z0-9]{20,}\b/g, "gh_REDACTED");
  // Slack tokens
  out = out.replace(/\bxox[baprs]-[A-Za-z0-9-]{10,}\b/g, "xox-REDACTED");
  // AWS access keys
  out = out.replace(/\bAKIA[0-9A-Z]{16}\b/g, "AKIAREDACTED00000000");
  // long hex-like tokens
  out = out.replace(/\b[a-f0-9]{32,}\b/gi, (m) => `${m.slice(0, 6)}…REDACTED…${m.slice(-4)}`);
  // Discord bot tokens often look like 3 base64-ish parts separated by dots.
  out = out.replace(/\b[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{20,}\b/g, "DISCORD_TOKEN_REDACTED");

  return out;
}

function detectSecrets(text) {
  const t = String(text ?? "");
  if (!t) return false;
  if (/\bsk-[A-Za-z0-9_-]{10,}\b/.test(t)) return true;
  if (/\bAKIA[0-9A-Z]{16}\b/.test(t)) return true;
  if (/\bxox[baprs]-[A-Za-z0-9-]{10,}\b/.test(t)) return true;
  if (/\bgh[pousr]_[A-Za-z0-9]{20,}\b/.test(t)) return true;
  if (/\b[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{20,}\b/.test(t)) return true;
  if (/([?&]token=)[^\\s&#]+/i.test(t)) return true;
  return false;
}

async function loadManagedChannels() {
  if (managedChannelsCache) return managedChannelsCache;
  const raw = await fsp.readFile(MANAGED_CHANNELS_PATH, "utf8").catch(() => null);
  if (!raw) {
    managedChannelsCache = [];
    return managedChannelsCache;
  }
  const parsed = safeParseJson(raw);
  const list = Array.isArray(parsed) ? parsed : [];
  managedChannelsCache = list
    .map((e) => ({ guild_id: String(e.guild_id ?? ""), channel_id: String(e.channel_id ?? "") }))
    .filter((e) => isStringId(e.guild_id) && isStringId(e.channel_id));
  return managedChannelsCache;
}

async function loadPolicies() {
  if (policiesCache) return policiesCache;
  const raw = await fsp.readFile(POLICIES_PATH, "utf8").catch(() => "");
  const allowNonAdminGlobalRead = /allow_non_admin_global_read:\s*true/i.test(raw);
  policiesCache = { allowNonAdminGlobalRead };
  return policiesCache;
}

export async function isManagedChannel({ guildId, channelId }) {
  if (!isStringId(String(guildId)) || !isStringId(String(channelId))) return false;
  const list = await loadManagedChannels();
  return list.some((e) => e.guild_id === String(guildId) && e.channel_id === String(channelId));
}

async function ensureAllowlistFile({ guildId, channelId }) {
  const p = allowlistPathForChannel(channelId);
  const existing = await readJsonFile(p);
  if (existing && existing.channel_id === String(channelId)) return existing;
  const obj = {
    guild_id: String(guildId),
    channel_id: String(channelId),
    admin_user_id: ADMIN_USER_ID,
    users: {}
  };
  await writeJsonAtomic(p, obj);
  return obj;
}

async function loadAllowlist({ guildId, channelId }) {
  const p = allowlistPathForChannel(channelId);
  const existing = await readJsonFile(p);
  if (existing && existing.channel_id === String(channelId)) return existing;
  return await ensureAllowlistFile({ guildId, channelId });
}

async function saveAllowlist(channelId, obj) {
  const p = allowlistPathForChannel(channelId);
  await writeJsonAtomic(p, obj);
  // also keep a copy for admin browsing in global/
  const globalCopy = path.join(GLOBAL_ROOT, `channel_allowlist_${channelId}.json`);
  await writeJsonAtomic(globalCopy, obj);
}

function upsertAllowlistUser(allowlist, userId, patch) {
  if (!allowlist.users || typeof allowlist.users !== "object") allowlist.users = {};
  const existing = allowlist.users[userId] && typeof allowlist.users[userId] === "object" ? allowlist.users[userId] : {};
  allowlist.users[userId] = { ...existing, ...patch };
}

async function ensureUserFolder(userId) {
  const dir = userDir(userId);
  await fsp.mkdir(dir, { recursive: true, mode: 0o700 });
  await fsp.mkdir(secretsDir(userId), { recursive: true, mode: 0o700 });

  const soulPath = userFile(userId, "sub-soul.md");
  const eventsPath = userFile(userId, "events.log");
  const profilePath = userFile(userId, "profile.json");

  // sub-soul.md (idempotent)
  await fsp
    .access(soulPath, fs.constants.F_OK)
    .catch(async () => {
      const header =
        `# sub-soul.md\n\n` +
        `User: ${userId}\n` +
        `Created: ${isoNow()}\n\n` +
        `Rules:\n` +
        `- Do not store credentials, tokens, or API keys here.\n` +
        `- This file may be readable by other non-admin users (with redaction).\n\n`;
      await fsp.writeFile(soulPath, header, { mode: 0o600 });
    });

  // events.log (append-only)
  await fsp.access(eventsPath, fs.constants.F_OK).catch(async () => {
    await fsp.writeFile(eventsPath, "", { mode: 0o600 });
  });

  // profile.json (idempotent)
  const existing = await readJsonFile(profilePath);
  if (!existing) {
    const profile = {
      user_id: userId,
      created_at: isoNow(),
      last_seen_at: null,
      memberships: {}
    };
    await writeJsonAtomic(profilePath, profile);
  }
}

function emailConfigPath(userId) {
  return path.join(secretsDir(userId), "email_imap.json");
}

function emailOauthConfigPath(userId) {
  return path.join(secretsDir(userId), "email_gmail_oauth.json");
}

function gmailOauthPendingPath(userId) {
  return path.join(secretsDir(userId), "gmail_oauth_pending.json");
}

function gmailOauthTokenPath(userId) {
  return path.join(secretsDir(userId), "gmail_oauth_token.json");
}

function anthropicModelPath(userId) {
  return path.join(secretsDir(userId), "anthropic_model.txt");
}

function anthropicSystemPath(userId) {
  return path.join(secretsDir(userId), "anthropic_system.txt");
}

async function isActiveManagedUser(userId) {
  const u = normalizeUserId(userId);
  if (!isStringId(u)) return false;
  if (u === ADMIN_USER_ID) return true;
  const list = await loadManagedChannels();
  for (const entry of list) {
    const allowlist = await loadAllowlist({ guildId: entry.guild_id, channelId: entry.channel_id }).catch(() => null);
    const status = allowlist?.users?.[u]?.status;
    if (status === "active") return true;
  }
  return false;
}

async function setUserEmailConfigGmail({ actorUserId, email, appPassword }) {
  const u = normalizeUserId(actorUserId);
  if (!isStringId(u)) return { ok: false, error: "Denied: unknown actor_user_id" };
  const e = String(email ?? "").trim();
  const pw = String(appPassword ?? "").trim();
  if (!e || !pw) return { ok: false, error: "Usage: email setup gmail <email> <app_password>" };
  await ensureUserFolder(u);
  const cfg = {
    kind: "imap",
    provider: "gmail",
    username: e,
    password: pw,
    imap: { host: "imap.gmail.com", port: 993, ssl: true }
  };
  await writeJsonAtomic(emailConfigPath(u), cfg);
  await appendEventsLog(u, `[${isoNow()}] email setup provider=gmail`);
  return { ok: true };
}

async function clearUserEmailConfig({ actorUserId }) {
  const u = normalizeUserId(actorUserId);
  if (!isStringId(u)) return { ok: false, error: "Denied: unknown actor_user_id" };
  await fsp.unlink(emailConfigPath(u)).catch(() => {});
  await fsp.unlink(emailOauthConfigPath(u)).catch(() => {});
  await fsp.unlink(gmailOauthPendingPath(u)).catch(() => {});
  await fsp.unlink(gmailOauthTokenPath(u)).catch(() => {});
  await appendEventsLog(u, `[${isoNow()}] email clear`);
  return { ok: true };
}

// Admin-only: bind an existing Gmail OAuth token (already present on this machine) to a tenancy user.
async function bindUserEmailConfigGmailOauth({ actorUserId, targetUserId, email }) {
  const actor = normalizeUserId(actorUserId);
  const target = normalizeUserId(targetUserId);
  if (!isStringId(actor) || !isStringId(target)) return { ok: false, error: "Denied: invalid user id" };
  if (actor !== ADMIN_USER_ID) return { ok: false, error: "Denied: admin only" };

  const e = String(email ?? "").trim().toLowerCase();
  if (!e || !e.includes("@")) return { ok: false, error: "Usage: tenancy bind-gmail-oauth <discord_user_id> <gmail_address>" };

  const safe = e.replace(/[^\w\-.]/g, "_");
  const srcToken = `/root/.codex/skills/gmail-skill/tokens/token_${safe}.json`;
  const dstToken = path.join(secretsDir(target), "gmail_oauth_token.json");
  const credsPath = "/root/.codex/skills/gmail-skill/credentials.json";

  await ensureUserFolder(target);
  await fsp.mkdir(secretsDir(target), { recursive: true, mode: 0o700 });

  const srcExists = await fsp.stat(srcToken).then(() => true).catch(() => false);
  const credsExists = await fsp.stat(credsPath).then(() => true).catch(() => false);
  if (!credsExists) return { ok: false, error: "Missing OAuth client credentials.json on server" };
  if (!srcExists) return { ok: false, error: `No OAuth token found for ${e} on server` };

  const tokenRaw = await fsp.readFile(srcToken, "utf8");
  await fsp.writeFile(dstToken, tokenRaw, { encoding: "utf8", mode: 0o600 });

  const cfg = {
    kind: "gmail_oauth",
    provider: "gmail",
    email: e,
    oauth_credentials_path: credsPath,
    oauth_token_path: dstToken,
    scopes: [
      "https://www.googleapis.com/auth/gmail.readonly",
      "https://www.googleapis.com/auth/gmail.modify",
      "https://www.googleapis.com/auth/gmail.send"
    ]
  };
  await writeJsonAtomic(emailOauthConfigPath(target), cfg);
  await appendEventsLog(target, `[${isoNow()}] email setup provider=gmail kind=gmail_oauth`);
  return { ok: true };
}

async function loadUserEmailMode({ actorUserId }) {
  const u = normalizeUserId(actorUserId);
  if (!isStringId(u)) return { kind: null, cfgPath: null };
  const pOauth = emailOauthConfigPath(u);
  const pImap = emailConfigPath(u);
  const oauth = await fsp.readFile(pOauth, "utf8").catch(() => "");
  if (oauth) return { kind: "gmail_oauth", cfgPath: pOauth };
  const imap = await fsp.readFile(pImap, "utf8").catch(() => "");
  if (imap) return { kind: "imap", cfgPath: pImap };
  return { kind: null, cfgPath: null };
}

async function runEmailGmailOauth({ actorUserId, args, cfgPath }) {
  const script = "/root/.openclaw/agents/main/tenancy/scripts/email_gmail_api.py";
  const venvPy = "/root/.codex/skills/gmail-skill/.venv/bin/python";
  const pythonBin = await fsp.stat(venvPy).then(() => venvPy).catch(() => "python3");
  const fullArgs = ["--config", cfgPath, ...args];

  return await new Promise((resolve, reject) => {
    const child = spawn(pythonBin, [script, ...fullArgs], { stdio: ["ignore", "pipe", "pipe"] });
    let out = "";
    let err = "";
    child.stdout.on("data", (b) => (out += b.toString("utf8")));
    child.stderr.on("data", (b) => (err += b.toString("utf8")));
    child.on("error", (e) => reject(e));
    child.on("close", (code) => {
      if (code !== 0) return reject(new Error(`email command failed (${code})`));
      try {
        resolve(JSON.parse(out));
      } catch {
        reject(new Error("email command returned invalid json"));
      }
    });
  });
}

async function runEmail({ actorUserId, args }) {
  const u = normalizeUserId(actorUserId);
  if (!isStringId(u)) throw new Error("Denied: unknown actor_user_id");
  await ensureUserFolder(u);
  const mode = await loadUserEmailMode({ actorUserId: u });
  if (!mode.kind || !mode.cfgPath) throw new Error("Email not configured. DM: `email setup gmail <email> <app_password>` (IMAP) or ask admin to bind OAuth.");
  if (mode.kind === "imap") return await runEmailImap({ actorUserId: u, args });
  if (mode.kind === "gmail_oauth") return await runEmailGmailOauth({ actorUserId: u, args, cfgPath: mode.cfgPath });
  throw new Error("Email not configured.");
}

async function startGmailOauthLink({ actorUserId, loginHint }) {
  const u = normalizeUserId(actorUserId);
  if (!isStringId(u)) return { ok: false, error: "Denied: unknown actor_user_id" };
  await ensureUserFolder(u);

  const script = "/root/.openclaw/agents/main/tenancy/scripts/gmail_oauth_link.py";
  const credsPath = "/root/.codex/skills/gmail-skill/credentials.json";
  const pendingPath = gmailOauthPendingPath(u);
  const args = ["auth-start", "--creds", credsPath, "--pending", pendingPath];
  if (loginHint) args.push("--login-hint", String(loginHint));

  return await new Promise((resolve) => {
    const child = spawn("python3", [script, ...args], { stdio: ["ignore", "pipe", "pipe"] });
    let out = "";
    child.stdout.on("data", (b) => (out += b.toString("utf8")));
    child.on("close", () => {
      try { resolve(JSON.parse(out)); } catch { resolve({ ok: false, error: "auth-start returned invalid json" }); }
    });
  });
}

async function finishGmailOauthLink({ actorUserId, callbackUrl }) {
  const u = normalizeUserId(actorUserId);
  if (!isStringId(u)) return { ok: false, error: "Denied: unknown actor_user_id" };
  await ensureUserFolder(u);

  const script = "/root/.openclaw/agents/main/tenancy/scripts/gmail_oauth_link.py";
  const credsPath = "/root/.codex/skills/gmail-skill/credentials.json";
  const pendingPath = gmailOauthPendingPath(u);
  const tokenOut = gmailOauthTokenPath(u);
  const args = ["auth-finish", "--creds", credsPath, "--pending", pendingPath, "--token-out", tokenOut, "--callback-url", String(callbackUrl)];

  const res = await new Promise((resolve) => {
    const child = spawn("python3", [script, ...args], { stdio: ["ignore", "pipe", "pipe"] });
    let out = "";
    child.stdout.on("data", (b) => (out += b.toString("utf8")));
    child.on("close", () => {
      try { resolve(JSON.parse(out)); } catch { resolve({ ok: false, error: "auth-finish returned invalid json" }); }
    });
  });

  if (!res.ok) return res;

  const email = String(res.email ?? "").trim().toLowerCase();
  if (!email || !email.includes("@")) return { ok: false, error: "OAuth finished but could not determine email" };

  const cfg = {
    kind: "gmail_oauth",
    provider: "gmail",
    email,
    oauth_credentials_path: credsPath,
    oauth_token_path: tokenOut,
    scopes: [
      "https://www.googleapis.com/auth/gmail.readonly",
      "https://www.googleapis.com/auth/gmail.modify",
      "https://www.googleapis.com/auth/gmail.send"
    ]
  };
  await writeJsonAtomic(emailOauthConfigPath(u), cfg);
  await appendEventsLog(u, `[${isoNow()}] email setup provider=gmail kind=gmail_oauth`);
  return { ok: true, email };
}

async function readTextFile(p) {
  const raw = await fsp.readFile(p, "utf8").catch(() => "");
  return String(raw ?? "").trim();
}

async function writeTextFile(p, text) {
  await fsp.mkdir(path.dirname(p), { recursive: true, mode: 0o700 });
  await fsp.writeFile(p, `${String(text ?? "").trim()}\n`, { mode: 0o600 });
}

async function runAnthropicChat({ actorUserId, prompt, model, system }) {
  const u = normalizeUserId(actorUserId);
  if (!isStringId(u)) throw new Error("Denied: unknown actor_user_id");
  await ensureUserFolder(u);

  const keyPath = providerKeyPath(u, "anthropic");
  const apiKey = keyPath ? (await readTextFile(keyPath)) : "";
  if (!apiKey) throw new Error("Anthropic key not set. DM: `me api set anthropic <api_key>`");

  const script = "/root/.openclaw/agents/main/tenancy/scripts/anthropic_chat.py";
  const args = ["--model", model, "--prompt", prompt, "--max-tokens", "2048"];
  if (system) args.push("--system", system);

  return await new Promise((resolve, reject) => {
    const child = spawn("python3", [script, ...args], {
      stdio: ["ignore", "pipe", "pipe"],
      env: { ...process.env, ANTHROPIC_API_KEY: apiKey }
    });
    let out = "";
    let err = "";
    child.stdout.on("data", (b) => (out += b.toString("utf8")));
    child.stderr.on("data", (b) => (err += b.toString("utf8")));
    child.on("error", (e) => reject(e));
    child.on("close", (code) => {
      if (code !== 0) return reject(new Error(`anthropic failed (${code})`));
      try {
        resolve(JSON.parse(out));
      } catch (e) {
        reject(new Error("anthropic returned invalid json"));
      }
    });
  });
}

// DM bootstrap: if a user can VIEW_CHANNEL in any managed channel, mark them active so they can use DM commands.
async function tryAutoVerifyManagedUser(userId) {
  const u = normalizeUserId(userId);
  if (!isStringId(u)) return false;
  if (u === ADMIN_USER_ID) return true;
  if (!discordApi) return false;

  const list = await loadManagedChannels();
  const now = isoNow();
  let verified = false;

  for (const entry of list) {
    const v = await verifyUserCanViewChannel({ guildId: entry.guild_id, channelId: entry.channel_id, userId: u }).catch(() => ({ ok: false }));
    if (!v.ok) continue;

    const allowlist = await loadAllowlist({ guildId: entry.guild_id, channelId: entry.channel_id }).catch(() => null);
    if (!allowlist) continue;

    upsertAllowlistUser(allowlist, u, {
      added_at: allowlist.users?.[u]?.added_at ?? now,
      last_seen_at: now,
      status: "active",
      roles: v.memberRoleIds?.slice(0, 100) ?? allowlist.users?.[u]?.roles,
      notes: void 0
    });
    await saveAllowlist(entry.channel_id, allowlist);
    await ensureUserFolder(u);
    await updateUserProfileSeen(u, { guildId: entry.guild_id, channelId: entry.channel_id, seenAt: now });
    await ensureServerIndex(entry.guild_id, u, entry.channel_id);
    verified = true;
  }

  return verified;
}

async function runEmailImap({ actorUserId, args }) {
  const u = normalizeUserId(actorUserId);
  if (!isStringId(u)) throw new Error("Denied: unknown actor_user_id");
  const cfgPath = emailConfigPath(u);
  const raw = await fsp.readFile(cfgPath, "utf8").catch(() => null);
  if (!raw) throw new Error("Email not configured. DM: `email setup gmail <email> <app_password>`");

  const script = "/root/.openclaw/agents/main/tenancy/scripts/email_imap.py";
  const fullArgs = ["--config", cfgPath, ...args];

  return await new Promise((resolve, reject) => {
    const child = spawn("python3", [script, ...fullArgs], {
      stdio: ["ignore", "pipe", "pipe"]
    });
    let out = "";
    let err = "";
    child.stdout.on("data", (b) => (out += b.toString("utf8")));
    child.stderr.on("data", (b) => (err += b.toString("utf8")));
    child.on("error", (e) => reject(e));
    child.on("close", (code) => {
      if (code !== 0) return reject(new Error(`email command failed (${code})`));
      try {
        const obj = JSON.parse(out);
        resolve(obj);
      } catch (e) {
        reject(new Error("email command returned invalid json"));
      }
    });
  });
}

export async function getUserApiKey({ actorUserId, provider }) {
  const u = normalizeUserId(actorUserId);
  if (!isStringId(u)) return null;
  const p = providerKeyPath(u, provider);
  if (!p) return null;
  const raw = await fsp.readFile(p, "utf8").catch(() => null);
  const key = raw ? raw.trim() : "";
  return key || null;
}

async function setUserApiKey({ actorUserId, provider, apiKey }) {
  const u = normalizeUserId(actorUserId);
  if (!isStringId(u)) return { ok: false, error: "Denied: unknown actor_user_id" };
  const name = providerKeyFileName(provider);
  if (!name) return { ok: false, error: "Usage: provider required" };
  const key = String(apiKey ?? "").trim();
  if (!key) return { ok: false, error: "Usage: api key required" };
  await ensureUserFolder(u);
  const p = providerKeyPath(u, provider);
  await fsp.writeFile(p, `${key}\n`, { mode: 0o600 });
  await appendEventsLog(u, `[${isoNow()}] api set provider=${provider}`);
  return { ok: true };
}

async function clearUserApiKey({ actorUserId, provider }) {
  const u = normalizeUserId(actorUserId);
  if (!isStringId(u)) return { ok: false, error: "Denied: unknown actor_user_id" };
  const name = providerKeyFileName(provider);
  if (!name) return { ok: false, error: "Usage: provider required" };
  const p = providerKeyPath(u, provider);
  if (!p) return { ok: false, error: "Usage: provider required" };
  await fsp.unlink(p).catch(() => {});
  await appendEventsLog(u, `[${isoNow()}] api clear provider=${provider}`);
  return { ok: true };
}

function randomSetupCode() {
  // Short, human-typable. Not a secret; only used to bind DM to the requester.
  return Math.random().toString(36).slice(2, 10);
}

async function startSetup({ actorUserId, provider }) {
  const u = normalizeUserId(actorUserId);
  if (!isStringId(u)) return { ok: false, error: "Denied: unknown actor_user_id" };
  const p = String(provider ?? "").trim().toLowerCase();
  if (!p) return { ok: false, error: "Usage: me setup <provider>" };
  await ensureUserFolder(u);
  const code = randomSetupCode();
  const payload = { provider: p, code, created_at: isoNow(), expires_at: new Date(Date.now() + SETUP_CODE_TTL_MS).toISOString() };
  const setupPath = path.join(secretsDir(u), "pending_setup.json");
  await writeJsonAtomic(setupPath, payload);
  await appendEventsLog(u, `[${isoNow()}] setup start provider=${p}`);
  return { ok: true, code, provider: p, expires_in_seconds: Math.floor(SETUP_CODE_TTL_MS / 1000) };
}

async function finishSetup({ actorUserId, provider, code, apiKey }) {
  const u = normalizeUserId(actorUserId);
  if (!isStringId(u)) return { ok: false, error: "Denied: unknown actor_user_id" };
  const p = String(provider ?? "").trim().toLowerCase();
  const c = String(code ?? "").trim();
  const k = String(apiKey ?? "").trim();
  if (!p || !c || !k) return { ok: false, error: "Usage: setup <provider> <code> <api_key>" };
  const setupPath = path.join(secretsDir(u), "pending_setup.json");
  const pending = await readJsonFile(setupPath);
  if (!pending || pending.provider !== p || pending.code !== c) return { ok: false, error: "Denied: invalid setup code" };
  const exp = Date.parse(String(pending.expires_at ?? ""));
  if (!Number.isFinite(exp) || Date.now() > exp) return { ok: false, error: "Denied: setup code expired" };
  const res = await setUserApiKey({ actorUserId: u, provider: p, apiKey: k });
  if (!res.ok) return res;
  await fsp.unlink(setupPath).catch(() => {});
  await appendEventsLog(u, `[${isoNow()}] setup finish provider=${p}`);
  return { ok: true };
}

async function updateUserProfileSeen(userId, { guildId, channelId, seenAt }) {
  const profilePath = userFile(userId, "profile.json");
  const profile = (await readJsonFile(profilePath)) ?? { user_id: userId, created_at: isoNow(), memberships: {} };
  profile.last_seen_at = seenAt;
  profile.memberships = profile.memberships && typeof profile.memberships === "object" ? profile.memberships : {};
  const g = (profile.memberships[guildId] && typeof profile.memberships[guildId] === "object") ? profile.memberships[guildId] : { channels: {} };
  g.channels = g.channels && typeof g.channels === "object" ? g.channels : {};
  const ch = (g.channels[channelId] && typeof g.channels[channelId] === "object") ? g.channels[channelId] : {};
  g.channels[channelId] = { ...ch, last_seen_at: seenAt };
  profile.memberships[guildId] = g;
  await writeJsonAtomic(profilePath, profile);
}

async function ensureServerIndex(guildId, userId, channelId) {
  const dir = path.join(SERVERS_ROOT, guildId, "users", userId);
  await fsp.mkdir(dir, { recursive: true, mode: 0o700 });
  const idxPath = path.join(dir, "index.json");
  const existing = (await readJsonFile(idxPath)) ?? {
    guild_id: guildId,
    user_id: userId,
    canonical_user_dir: userDir(userId),
    channels: {}
  };
  existing.channels = existing.channels && typeof existing.channels === "object" ? existing.channels : {};
  existing.channels[channelId] = { last_seen_at: isoNow() };
  await writeJsonAtomic(idxPath, existing);
}

export async function onDiscordMessageObserved({ guildId, channelId, userId, memberRoleIds }) {
  const g = String(guildId);
  const c = String(channelId);
  const u = normalizeUserId(userId);
  if (!isStringId(g) || !isStringId(c) || !isStringId(u)) return;
  if (!(await isManagedChannel({ guildId: g, channelId: c }))) return;

  const allowlist = await loadAllowlist({ guildId: g, channelId: c });
  const now = isoNow();

  const roles = Array.isArray(memberRoleIds) ? memberRoleIds.filter((r) => isStringId(String(r))).map(String) : void 0;
  const existing = allowlist.users?.[u];
  if (!existing) {
    // Deny until verified: observed users start as removed/unverified.
    upsertAllowlistUser(allowlist, u, {
      added_at: now,
      last_seen_at: now,
      status: "removed",
      roles: roles?.length ? roles : void 0,
      notes: "observed (unverified)"
    });
  } else {
    upsertAllowlistUser(allowlist, u, {
      last_seen_at: now,
      roles: roles?.length ? roles : existing.roles
    });
  }

  await saveAllowlist(c, allowlist);
}

const PERM_VIEW_CHANNEL = 1n << 10n;
const PERM_ADMINISTRATOR = 1n << 3n;

function toBigIntPerm(v) {
  try {
    if (typeof v === "bigint") return v;
    if (typeof v === "number") return BigInt(v);
    const s = String(v ?? "0").trim();
    if (!s) return 0n;
    return BigInt(s);
  } catch {
    return 0n;
  }
}

function computeBaseGuildPermissions({ guildId, rolesById, memberRoleIds }) {
  let perms = 0n;
  const everyone = rolesById.get(guildId);
  if (everyone) perms |= toBigIntPerm(everyone.permissions);
  for (const rid of memberRoleIds) {
    const role = rolesById.get(rid);
    if (role) perms |= toBigIntPerm(role.permissions);
  }
  return perms;
}

function applyOverwrite(perms, deny, allow) {
  const d = toBigIntPerm(deny);
  const a = toBigIntPerm(allow);
  return (perms & ~d) | a;
}

// Discord permission overwrite rules (simplified, sufficient for VIEW_CHANNEL checks).
function computeChannelPermissions({ guildId, userId, basePerms, overwrites, memberRoleIds }) {
  let perms = basePerms;
  if ((perms & PERM_ADMINISTRATOR) === PERM_ADMINISTRATOR) return perms;

  const ow = Array.isArray(overwrites) ? overwrites : [];

  // 1) @everyone overwrite (role id == guild id)
  const everyoneOw = ow.find((o) => String(o.id) === String(guildId));
  if (everyoneOw) perms = applyOverwrite(perms, everyoneOw.deny, everyoneOw.allow);

  // 2) role overwrites (aggregate)
  let roleDeny = 0n;
  let roleAllow = 0n;
  for (const o of ow) {
    if (String(o.type) !== "0") continue; // role
    const id = String(o.id);
    if (!memberRoleIds.includes(id)) continue;
    roleDeny |= toBigIntPerm(o.deny);
    roleAllow |= toBigIntPerm(o.allow);
  }
  perms = applyOverwrite(perms, roleDeny, roleAllow);

  // 3) member overwrite
  const memberOw = ow.find((o) => String(o.type) === "1" && String(o.id) === String(userId));
  if (memberOw) perms = applyOverwrite(perms, memberOw.deny, memberOw.allow);

  return perms;
}

async function verifyUserCanViewChannel({ guildId, channelId, userId }) {
  if (!discordApi) return { ok: false, reason: "discordApi not set" };

  const channel = await discordApi.fetchChannel(channelId).catch(() => null);
  if (!channel) return { ok: false, reason: "channel fetch failed" };
  if (String(channel.guild_id ?? "") !== String(guildId)) return { ok: false, reason: "channel guild mismatch" };

  const roles = await discordApi.fetchRoles(guildId).catch(() => null);
  if (!Array.isArray(roles)) return { ok: false, reason: "roles fetch failed" };

  const member = await discordApi.fetchMember(guildId, userId).catch(() => null);
  if (!member) return { ok: false, reason: "member fetch failed" };

  const rolesById = new Map(roles.map((r) => [String(r.id), r]));
  const memberRoleIds = [guildId, ...(Array.isArray(member.roles) ? member.roles.map(String) : [])];
  const basePerms = computeBaseGuildPermissions({ guildId, rolesById, memberRoleIds });
  const effective = computeChannelPermissions({
    guildId,
    userId,
    basePerms,
    overwrites: channel.permission_overwrites,
    memberRoleIds
  });

  const canView = (effective & PERM_VIEW_CHANNEL) === PERM_VIEW_CHANNEL || (effective & PERM_ADMINISTRATOR) === PERM_ADMINISTRATOR;
  return { ok: canView, memberRoleIds };
}

async function syncOneChannel({ guildId, channelId }) {
  const allowlist = await loadAllowlist({ guildId, channelId });
  const now = isoNow();

  // Candidates: existing users + recent authors.
  const candidates = new Set(Object.keys(allowlist.users ?? {}));
  const recent = await discordApi.fetchRecentMessages(channelId, RECENT_MSG_LIMIT).catch(() => []);
  for (const msg of Array.isArray(recent) ? recent : []) {
    const uid = String(msg?.author?.id ?? "");
    if (isStringId(uid)) candidates.add(uid);
  }

  for (const uid of candidates) {
    const v = await verifyUserCanViewChannel({ guildId, channelId, userId: uid }).catch(() => ({ ok: false }));
    if (!v.ok) {
      // mark removed (do not delete user folders)
      const prev = allowlist.users?.[uid];
      upsertAllowlistUser(allowlist, uid, {
        added_at: prev?.added_at ?? now,
        last_seen_at: prev?.last_seen_at ?? null,
        status: "removed",
        roles: prev?.roles ?? void 0,
        notes: prev?.notes ?? "removed (not verified)"
      });
      continue;
    }

    const prevStatus = allowlist.users?.[uid]?.status;
    upsertAllowlistUser(allowlist, uid, {
      added_at: allowlist.users?.[uid]?.added_at ?? now,
      last_seen_at: allowlist.users?.[uid]?.last_seen_at ?? now,
      status: "active",
      roles: v.memberRoleIds?.slice(0, 100) ?? allowlist.users?.[uid]?.roles,
      notes: void 0
    });

    if (prevStatus !== "active") {
      await ensureUserFolder(uid);
      await updateUserProfileSeen(uid, { guildId, channelId, seenAt: now });
    }
    await ensureServerIndex(guildId, uid, channelId);
  }

  await saveAllowlist(channelId, allowlist);
}

async function syncAll() {
  const list = await loadManagedChannels();
  for (const entry of list) await syncOneChannel({ guildId: entry.guild_id, channelId: entry.channel_id });
}

export async function ensureStarted({ api }) {
  if (started) return;
  discordApi = api;
  started = true;
  // initial sync (best effort; errors should not crash gateway)
  syncAll().catch(() => {});
  syncTimer = setInterval(() => {
    syncAll().catch(() => {});
  }, SYNC_EVERY_MS);
  // allow clean exit
  if (typeof syncTimer.unref === "function") syncTimer.unref();
}

export async function syncNow({ channelId } = {}) {
  const list = await loadManagedChannels();
  if (channelId) {
    const match = list.find((e) => e.channel_id === String(channelId));
    if (!match) return { ok: false, error: "unknown channel_id" };
    await syncOneChannel({ guildId: match.guild_id, channelId: match.channel_id });
    return { ok: true, channels: [match.channel_id] };
  }
  await syncAll();
  return { ok: true, channels: list.map((e) => e.channel_id) };
}

function isUnder(dir, p) {
  const rel = path.relative(dir, p);
  return rel === "" || (!rel.startsWith("..") && !path.isAbsolute(rel));
}

export async function writeGuard({ actorUserId, absPath }) {
  const u = normalizeUserId(actorUserId);
  if (!isStringId(u)) return { ok: false, error: "Denied: unknown actor_user_id" };
  if (u === ADMIN_USER_ID) return { ok: true };

  const own = userDir(u);
  if (!isUnder(own, absPath)) return { ok: false, error: "Denied: non-admin may only write inside their own tenancy folder" };
  return { ok: true };
}

export async function readGuard({ actorUserId, absPath, content }) {
  const u = normalizeUserId(actorUserId);
  if (!isStringId(u)) return { ok: false, error: "Denied: unknown actor_user_id" };
  const isAdmin = u === ADMIN_USER_ID;
  const policies = await loadPolicies();

  if (!isAdmin) {
    if (looksSensitivePath(absPath)) return { ok: false, error: "Contains sensitive material; redacted" };
    if (isUnder(GLOBAL_ROOT, absPath) && !policies.allowNonAdminGlobalRead) {
      return { ok: false, error: "Denied: global tenancy reads are disabled by policy" };
    }
    if (!isUnder(USERS_ROOT, absPath) && !isUnder(GLOBAL_ROOT, absPath)) {
      return { ok: false, error: "Denied: read outside tenancy scope" };
    }
  }

  const raw = String(content ?? "");
  if (!raw) return { ok: true, content: raw, redacted: false };

  const hasSecrets = detectSecrets(raw);
  if (hasSecrets) {
    if (looksSensitivePath(absPath)) return { ok: false, error: "Contains sensitive material; redacted" };
    const redacted = redactText(raw);
    return { ok: true, content: redacted, redacted: redacted !== raw };
  }
  // Even when not detected, still apply output redaction as a safety net.
  const redacted = redactText(raw);
  return { ok: true, content: redacted, redacted: redacted !== raw };
}

async function appendEventsLog(userId, line) {
  const p = userFile(userId, "events.log");
  const safe = redactText(line);
  await fsp.appendFile(p, safe.endsWith("\n") ? safe : `${safe}\n`, { encoding: "utf8", mode: 0o600 });
}

function parseCommand(text) {
  const t = String(text ?? "").trim();
  if (!t) return null;
  const cleaned = t.startsWith("/") ? t.slice(1) : t;
  const parts = cleaned.split(/\s+/).filter(Boolean);
  if (parts.length === 0) return null;
  return { parts, raw: cleaned };
}

function isCodingRelatedText(text) {
  const t = String(text ?? "").trim();
  if (!t) return false;
  if (/^(?:\/)?nodelegate\b/i.test(t) || /^no-delegate\s*:/i.test(t)) return false;

  // Strong signals
  if (t.includes("```")) return true;
  if (/\b(traceback|stack trace|stacktrace|exception|segfault)\b/i.test(t)) return true;
  if (/\b(error|fails?|failing|broken)\b/i.test(t) && /[:\n]/.test(t)) return true;
  if (/\b(build|compile|linker|lint|test suite|unit test|integration test)\b/i.test(t)) return true;

  // Product/app/game requests (common in Discord) that otherwise lack "code-y" keywords.
  // Keep this fairly conservative: require a build verb AND an app-ish noun.
  const buildVerb = /\b(create|make|build|ship|scaffold|generate)\b/i.test(t);
  const appNoun = /\b(app|application|expo|react\s*native|website|web\s*app|ui|frontend|game|tictactoe|tic\s*tac\s*toe)\b/i.test(t);
  if (buildVerb && appNoun) return true;

  // Common coding verbs + nouns
  const verb = /\b(implement|refactor|fix|debug|optimi[sz]e|rewrite|add|remove|rename|migrate|port)\b/i.test(t);
  const noun =
    /\b(api|endpoint|server|client|frontend|backend|discord|bot|gateway|systemd|docker|kubernetes|k8s|database|sql|schema|auth|oauth)\b/i.test(t);
  if (verb && noun) return true;

  // File/path hints
  if (/[^\s]+\.(js|ts|tsx|jsx|py|go|rs|java|kt|cpp|c|h|cs|rb|php|sh|yaml|yml|toml|json|md)\b/i.test(t)) return true;
  if (/[`'"]?\/(root|home|etc|usr|var)\//.test(t)) return true;

  // Commands
  if (/\b(npm|pnpm|yarn|pip|pip3|poetry|pytest|go test|cargo test|make|cmake|docker|git)\b/i.test(t)) return true;

  return false;
}

function extractUnifiedDiffFromText(text) {
  const s = String(text ?? "");
  const m = s.match(/```diff\s*([\s\S]*?)```/i);
  if (!m) return null;
  const diff = String(m[1] ?? "").trim();
  if (!diff) return null;
  // Basic sanity: unified diff usually contains ---/+++ lines.
  if (!/^---\s/m.test(diff) || !/^\+\+\+\s/m.test(diff)) return null;
  return diff;
}

async function extractWorkerTaskMeta(text) {
  const body = String(text ?? "");
  const { parseProtocolHeaderLine } = await protocol();

  // 1) Protocol header (legacy)
  // Scan first few lines, since the first line is often a mention.
  const lines = body.split(/\r?\n/);
  for (let i = 0; i < Math.min(lines.length, 5); i++) {
    const h = parseProtocolHeaderLine(lines[i]);
    if (h && h.owner === "OpenClaw" && h.task) return { task: h.task, mode: String(h.mode || "").toUpperCase() || null };
  }

  // 2) Human meta line from claudebot
  // Example: "Task: 20260210-001 (INFO)"
  for (let i = 0; i < Math.min(lines.length, 10); i++) {
    const m = lines[i].match(/\bTask\s*:\s*([A-Za-z0-9_.-]{6,})\s*(?:\((CALL|INFO|DONE|FAIL|HALT)\))?/i);
    if (m) return { task: m[1], mode: m[2] ? String(m[2]).toUpperCase() : null };
  }

  return { task: null, mode: null };
}

async function applyDiffAndTestWorkspace({ taskId, diff }) {
  const repo = "/root/.openclaw/workspace";
  const tmp = `/tmp/claudecode_${String(taskId ?? "task").replace(/[^\w.-]/g, "_")}.diff`;

  // Refuse suspicious / sensitive paths in diffs.
  // Only allow relative paths under the repo (a/..., b/...) and block common secret locations.
  const touched = [];
  for (const line of String(diff ?? "").split(/\r?\n/)) {
    const m = line.match(/^(?:\+\+\+|---)\s+(?:a\/|b\/)?(.+)$/);
    if (!m) continue;
    const p = String(m[1] ?? "").trim();
    if (!p || p === "/dev/null") continue;
    touched.push(p);
  }
  for (const p of touched) {
    if (p.startsWith("/") || p.includes("..") || p.includes("\\") || looksSensitivePath(p)) {
      return { ok: false, step: "path-guard", out: `Refused diff touching suspicious path: ${p}` };
    }
  }

  await fsp.writeFile(tmp, `${diff}\n`, { mode: 0o600 });

  const run = async (cmd, args, opts = {}) =>
    await new Promise((resolve) => {
      const child = spawn(cmd, args, { stdio: ["ignore", "pipe", "pipe"], ...opts });
      let out = "";
      let err = "";
      child.stdout.on("data", (b) => (out += b.toString("utf8")));
      child.stderr.on("data", (b) => (err += b.toString("utf8")));
      child.on("close", (code) => resolve({ code: code ?? 1, out, err }));
    });

  // Apply patch
  const check = await run("git", ["-C", repo, "apply", "--check", tmp]);
  if (check.code !== 0) {
    return {
      ok: false,
      step: "apply-check",
      out: redactText(check.out || check.err || "git apply --check failed").slice(0, 1500)
    };
  }

  const apply = await run("git", ["-C", repo, "apply", "--whitespace=nowarn", tmp]);
  if (apply.code !== 0) {
    return {
      ok: false,
      step: "apply",
      out: redactText(apply.out || apply.err || "git apply failed").slice(0, 1500)
    };
  }

  // Pick a simple test command based on common project markers.
  const exists = async (p) => await fsp.stat(path.join(repo, p)).then(() => true).catch(() => false);
  let testCmd = null;
  if (await exists("package.json")) testCmd = ["npm", ["-s", "test"]];
  else if ((await exists("pytest.ini")) || (await exists("pyproject.toml")) || (await exists("requirements.txt"))) testCmd = ["pytest", ["-q"]];
  else if (await exists("go.mod")) testCmd = ["go", ["test", "./..."]];
  else if (await exists("Cargo.toml")) testCmd = ["cargo", ["test"]];

  let testResult = null;
  if (testCmd) {
    const [bin, args] = testCmd;
    testResult = await run(bin, args, { cwd: repo });
  }

  const status = await run("git", ["-C", repo, "status", "--porcelain"]);
  return {
    ok: true,
    step: "done",
    test: testResult
      ? { code: testResult.code, out: redactText(testResult.out).slice(0, 1200), err: redactText(testResult.err).slice(0, 1200) }
      : null,
    status: redactText(status.out).slice(0, 1200)
  };
}

export async function handleMentionCommand(params) {
  const { guildId, channelId, actorUserId, text, sendReply } = params;
  const u = normalizeUserId(actorUserId);
  if (!isStringId(u)) return { handled: false };

  const managed = await isManagedChannel({ guildId, channelId }).catch(() => false);
  // Debug: trace bot-to-bot handoff without spamming normal users.
  if (u === CLAUDECODE_BOT_USER_ID || /\bTask\s*:\s*[A-Za-z0-9_.-]{6,}/i.test(String(text ?? ""))) {
    tenancyDebug(
      `[${isoNow()}] mentionCmd managed=${managed} guild=${String(guildId)} channel=${String(channelId)} actor=${u} text_head=${JSON.stringify(
        String(text ?? "").slice(0, 120)
      )}`
    );
  }

  if (!managed) return { handled: false };

  // ClaudeCode -> OpenClaw: consume worker outputs so they do not hit the LLM reply path.
  // ClaudeCode must only mention @OpenClaw; we never @ClaudeCode back unless calling it explicitly.
  if (CLAUDECODE_BOT_USER_ID && u === CLAUDECODE_BOT_USER_ID) {
    const body = String(text ?? "");
    const { task, mode } = await extractWorkerTaskMeta(body);
    {
      const need = [];
      for (const line of body.split(/\r?\n/)) {
        const idx = line.indexOf("NEED_INPUT:");
        if (idx >= 0) need.push(line.slice(idx + "NEED_INPUT:".length).trim());
      }
      if (need.length) {
        await sendReply(`ClaudeCode needs input${task ? ` for task ${task}` : ""}:\n- ${need.join("\n- ")}`.slice(0, 1800));
        return { handled: true };
      }
      // If ClaudeCode produced a diff, apply it to the OpenClaw workspace and run a lightweight test pass.
      // This keeps OpenClaw as "PM/driver": Claude writes code, OpenClaw applies + tests.
      if (mode === "INFO" || mode === "DONE" || mode === null) {
        const diff = extractUnifiedDiffFromText(body);
        if (diff) {
          await sendReply(`${task ? `[task:${task} mode:INFO owner:OpenClaw]\n` : ""}Applying patch + running tests in /root/.openclaw/workspace...`.slice(0, 900));
          void (async () => {
            const res = await applyDiffAndTestWorkspace({ taskId: task || "unknown", diff }).catch((e) => ({
              ok: false,
              step: "exception",
              out: redactText(String(e?.stack ?? e)).slice(0, 1200)
            }));
            if (res.ok) {
              const testLine = res.test ? `TEST: exit=${res.test.code}\n${(res.test.out || res.test.err || "").trim()}` : "TEST: (no runner detected)";
              await sendReply(
                [
                  task ? `[task:${task} mode:DONE owner:OpenClaw]` : "DONE:",
                  `Applied ClaudeCode patch to /root/.openclaw/workspace.`,
                  testLine,
                  res.status ? `GIT_STATUS:\n${res.status.trim()}` : ""
                ]
                  .filter(Boolean)
                  .join("\n")
                  .slice(0, 1800)
              );
              return;
            }
            await sendReply(
              [
                task ? `[task:${task} mode:FAIL owner:OpenClaw]` : "FAIL:",
                `Patch apply/test failed at step=${res.step}.`,
                res.out ? `DETAILS:\n${res.out.trim()}` : ""
              ]
                .filter(Boolean)
                .join("\n")
                .slice(0, 1800)
            );
          })();
          return { handled: true };
        }
      }

      // Default: no-op (mark handled so OpenClaw doesn't respond conversationally).
      if (["FAIL", "HALT"].includes(String(mode ?? "").toUpperCase())) {
        await sendReply(`ClaudeCode reported ${mode}${task ? ` for task ${task}` : ""}.`.slice(0, 500));
      }
      return { handled: true };
    }
  }

  const cmd = parseCommand(text);
  if (!cmd) return { handled: false };

  const head = cmd.parts[0]?.toLowerCase();
  const isAdmin = u === ADMIN_USER_ID;

  if (head === "claudecode" || head === "cc") {
    if (!CLAUDECODE_BOT_USER_ID) {
      await sendReply("ClaudeCode not configured. Set env `CLAUDECODE_BOT_USER_ID` for OpenClaw and restart.");
      return { handled: true };
    }
    const rest = cmd.raw.split(/\s+/).slice(1).join(" ").trim();
    if (!rest) {
      await sendReply("Usage: claudecode <what to do> (this will call @ClaudeCode)");
      return { handled: true };
    }
    const { nextTaskId, formatProtocolHeader } = await protocol();
    const taskId = await nextTaskId({ counterFilePath: path.join(GLOBAL_ROOT, "claudecode_task_counter.json") });
    const header = `||${formatProtocolHeader({ taskId, mode: "CALL", owner: "OpenClaw" })}||`;
    const payload =
      `<@${CLAUDECODE_BOT_USER_ID}>\n` +
      `Delegated to claudebot (task ${taskId}).\n` +
      `${header}\n` +
      `REQUEST:\n${rest}\n\n` +
      `CONTEXT:\n` +
      `- guild:${guildId}\n` +
      `- channel:${channelId}\n` +
      `- from_user:${u}\n`;
    await sendReply(payload.slice(0, 1800));
    return { handled: true };
  }

  // Default routing: delegate coding tasks to ClaudeCode automatically.
  // Keep it conservative to avoid noisy delegation for general chat.
  const explicitlyAsksForClaudeBot =
    (CLAUDECODE_BOT_USER_ID && String(text ?? "").includes(`<@${CLAUDECODE_BOT_USER_ID}>`)) ||
    /\bclaude\s*bot\b/i.test(String(text ?? "")) ||
    /\bclaudebot\b/i.test(String(text ?? ""));

  if (CLAUDECODE_BOT_USER_ID && (explicitlyAsksForClaudeBot || isCodingRelatedText(text))) {
    const { nextTaskId, formatProtocolHeader } = await protocol();
    const taskId = await nextTaskId({ counterFilePath: path.join(GLOBAL_ROOT, "claudecode_task_counter.json") });
    const header = `||${formatProtocolHeader({ taskId, mode: "CALL", owner: "OpenClaw" })}||`;
    const payload =
      `<@${CLAUDECODE_BOT_USER_ID}>\n` +
      `Delegated to claudebot (task ${taskId}).\n` +
      `${header}\n` +
      `REQUEST:\n${String(text ?? "").trim()}\n\n` +
      `CONTEXT:\n` +
      `- workspace:/root/.openclaw/workspace\n` +
      `- apply_patch: OpenClaw will apply unified diff and run tests if possible\n` +
      `- guild:${guildId}\n` +
      `- channel:${channelId}\n` +
      `- from_user:${u}\n`;
    await sendReply(payload.slice(0, 1800));
    return { handled: true };
  }

  // Non-admin commands
  if (head === "me") {
    await ensureUserFolder(u);
    const sub = (cmd.parts[1] ?? "").toLowerCase();
    const sub2 = (cmd.parts[2] ?? "").toLowerCase();
    if (sub === "setup") {
      const provider = cmd.parts[2] ? String(cmd.parts[2]).trim().toLowerCase() : "";
      const started = await startSetup({ actorUserId: u, provider });
      if (!started.ok) {
        await sendReply(redactText(started.error));
        return { handled: true };
      }
      // Tell them to DM the bot with the code. Do not accept API keys in public channels.
      await sendReply(
        `Setup started for provider=${provider}. ` +
          `DM me (in a Discord DM): \`setup ${provider} ${started.code} <your_api_key>\`. ` +
          `Code expires in ${started.expires_in_seconds}s.`
      );
      return { handled: true };
    }
    if (sub === "api" && sub2 === "status") {
      const providers = ["openai", "brave", "anthropic"];
      const statuses = {};
      for (const p of providers) statuses[p] = Boolean(await getUserApiKey({ actorUserId: u, provider: p }));
      await sendReply(redactText(JSON.stringify({ ok: true, api_keys: statuses })));
      return { handled: true };
    }
    if (sub === "api" && sub2 === "clear") {
      const provider = String(cmd.parts[3] ?? "").trim().toLowerCase();
      const res = await clearUserApiKey({ actorUserId: u, provider });
      await sendReply(res.ok ? "Cleared." : redactText(res.error));
      return { handled: true };
    }
    if (sub === "api" && sub2 === "set") {
      // Refuse in managed channels (public). Force DM-based setup.
      await sendReply("Denied: set API keys via DM only. Use `me setup <provider>`.");
      return { handled: true };
    }
    if (sub === "show") {
      const content = await fsp.readFile(userFile(u, "sub-soul.md"), "utf8").catch(() => "");
      const guarded = await readGuard({ actorUserId: u, absPath: userFile(u, "sub-soul.md"), content });
      if (!guarded.ok) {
        await sendReply(redactText(guarded.error));
        return { handled: true };
      }
      await sendReply(guarded.content.slice(0, 3500));
      return { handled: true };
    }
    if (sub === "save") {
      const body = cmd.raw.split(/\s+/).slice(2).join(" ").trim();
      if (!body) {
        await sendReply("Usage: me save <text>");
        return { handled: true };
      }
      const guard = await writeGuard({ actorUserId: u, absPath: userFile(u, "sub-soul.md") });
      if (!guard.ok) {
        await sendReply(redactText(guard.error));
        return { handled: true };
      }
      await fsp.appendFile(userFile(u, "sub-soul.md"), `${redactText(body)}\n`, "utf8");
      await appendEventsLog(u, `[${isoNow()}] me save (${body.length} chars)`);
      await sendReply("Saved.");
      return { handled: true };
    }
    if (sub === "reset") {
      const guard = await writeGuard({ actorUserId: u, absPath: userFile(u, "sub-soul.md") });
      if (!guard.ok) {
        await sendReply(redactText(guard.error));
        return { handled: true };
      }
      const header =
        `# sub-soul.md\n\n` +
        `User: ${u}\n` +
        `Reset: ${isoNow()}\n\n` +
        `Rules:\n` +
        `- Do not store credentials, tokens, or API keys here.\n` +
        `- This file may be readable by other non-admin users (with redaction).\n\n`;
      await fsp.writeFile(userFile(u, "sub-soul.md"), header, { mode: 0o600 });
      await appendEventsLog(u, `[${isoNow()}] me reset`);
      await sendReply("Reset.");
      return { handled: true };
    }
    return { handled: false };
  }

  if (head === "email") {
    // Avoid leaking private email contents in public channels.
    // Email commands are supported via DM only (see handleDmCommand).
    await sendReply(
      "Email commands run in Discord DM only (privacy). " +
      "DM me one of:\n" +
      "- `email setup gmail <your_email> <gmail_app_password>`\n" +
      "- `email oauth-start <your_gmail>` (recommended)\n" +
      "- `email inbox [limit=5]`\n" +
      "- `email unread [limit=5]`\n" +
      "- `email read <id>`\n" +
      "- `email search <query>`\n" +
      "- `email send to=<addr> subject=<text> body=<text> confirm=yes` (OAuth only)\n" +
      "- `email clear`"
    );
    return { handled: true };
  }

  if (head === "user" && cmd.parts[1]?.toLowerCase() === "read") {
    const targetUserId = String(cmd.parts[2] ?? "").trim();
    if (!isStringId(targetUserId)) {
      await sendReply("Usage: user read <user_id> [file=sub-soul.md]");
      return { handled: true };
    }
    const fileArg = cmd.parts.find((p) => p.toLowerCase().startsWith("file="));
    const fileName = (fileArg ? fileArg.split("=", 2)[1] : "sub-soul.md") || "sub-soul.md";
    const safeName = path.basename(fileName);
    const abs = userFile(targetUserId, safeName);
    const content = await fsp.readFile(abs, "utf8").catch(() => "");
    const guarded = await readGuard({ actorUserId: u, absPath: abs, content });
    if (!guarded.ok) {
      await sendReply(redactText(guarded.error));
      return { handled: true };
    }
    await sendReply(guarded.content.slice(0, 3500));
    return { handled: true };
  }

  // Admin commands
  if (head === "tenancy") {
    if (!isAdmin) {
      await sendReply("Denied: admin only.");
      return { handled: true };
    }
    const sub = (cmd.parts[1] ?? "").toLowerCase();
    if (sub === "sync-now") {
      const maybeChannel = cmd.parts[2] && isStringId(cmd.parts[2]) ? cmd.parts[2] : null;
      const res = await syncNow({ channelId: maybeChannel ?? void 0 }).catch((e) => ({ ok: false, error: String(e) }));
      await sendReply(redactText(JSON.stringify(res)));
      return { handled: true };
    }
    if (sub === "bind-gmail-oauth") {
      const targetUserId = String(cmd.parts[2] ?? "").trim();
      const gmail = String(cmd.parts[3] ?? "").trim();
      const res = await bindUserEmailConfigGmailOauth({ actorUserId: u, targetUserId, email: gmail }).catch((e) => ({ ok: false, error: String(e) }));
      await sendReply(redactText(JSON.stringify(res)));
      return { handled: true };
    }
    if (sub === "list-users") {
      const maybeChannel = cmd.parts[2] && isStringId(cmd.parts[2]) ? cmd.parts[2] : channelId;
      const allowlist = await loadAllowlist({ guildId, channelId: maybeChannel }).catch(() => null);
      if (!allowlist) {
        await sendReply("No allowlist.");
        return { handled: true };
      }
      const users = Object.entries(allowlist.users ?? {}).map(([id, urec]) => ({ id, status: urec?.status ?? "unknown", last_seen_at: urec?.last_seen_at ?? null }));
      await sendReply(redactText(JSON.stringify({ channel_id: maybeChannel, users })));
      return { handled: true };
    }
    if (sub === "inspect") {
      const targetUserId = String(cmd.parts[2] ?? "").trim();
      if (!isStringId(targetUserId)) {
        await sendReply("Usage: tenancy inspect <user_id>");
        return { handled: true };
      }
      const p = userFile(targetUserId, "profile.json");
      const raw = await fsp.readFile(p, "utf8").catch(() => "");
      const guarded = await readGuard({ actorUserId: u, absPath: p, content: raw });
      if (!guarded.ok) {
        await sendReply(redactText(guarded.error));
        return { handled: true };
      }
      await sendReply(guarded.content.slice(0, 3500));
      return { handled: true };
    }
    if (sub === "set-policy") {
      const key = (cmd.parts[2] ?? "").toLowerCase();
      const value = (cmd.parts[3] ?? "").toLowerCase();
      if (key !== "allow_non_admin_global_read" || !["true", "false"].includes(value)) {
        await sendReply("Usage: tenancy set-policy allow_non_admin_global_read true|false");
        return { handled: true };
      }
      const raw = await fsp.readFile(POLICIES_PATH, "utf8").catch(() => "");
      const next = raw.replace(/allow_non_admin_global_read:\\s*(true|false)/i, `allow_non_admin_global_read: ${value}`);
      await fsp.writeFile(POLICIES_PATH, next, { mode: 0o600 });
      policiesCache = null;
      await sendReply("Updated.");
      return { handled: true };
    }
    return { handled: false };
  }

  return { handled: false };
}

// Direct-message command handler (does not require mention).
export async function handleDmCommand(params) {
  const { actorUserId, text, sendReply } = params;
  const u = normalizeUserId(actorUserId);
  if (!isStringId(u)) return { handled: false };
  // Require that the user is verified (active) in at least one managed channel.
  // If they're not yet present in the allowlist, try to auto-verify via Discord permissions.
  if (!await isActiveManagedUser(u)) {
    const ok = await tryAutoVerifyManagedUser(u).catch(() => false);
    if (!ok) {
      await sendReply("Denied: you are not verified for managed channels.");
      return { handled: true };
    }
  }
  const cmd = parseCommand(text);
  if (!cmd) return { handled: false };

  const head = cmd.parts[0]?.toLowerCase();
  if (head === "setup") {
    const provider = String(cmd.parts[1] ?? "").trim().toLowerCase();
    const code = String(cmd.parts[2] ?? "").trim();
    const apiKey = cmd.raw.split(/\s+/).slice(3).join(" ").trim();
    const res = await finishSetup({ actorUserId: u, provider, code, apiKey });
    await sendReply(res.ok ? "Saved." : redactText(res.error));
    return { handled: true };
  }

  if (head === "email") {
    const sub = (cmd.parts[1] ?? "").toLowerCase();
    if (sub === "setup" && (cmd.parts[2] ?? "").toLowerCase() === "gmail") {
      const email = String(cmd.parts[3] ?? "").trim();
      const appPassword = cmd.raw.split(/\s+/).slice(4).join(" ").trim();
      const res = await setUserEmailConfigGmail({ actorUserId: u, email, appPassword });
      await sendReply(res.ok ? "Saved. Try: `email inbox`" : redactText(res.error));
      return { handled: true };
    }
    if (sub === "oauth-start") {
      const email = String(cmd.parts[2] ?? "").trim();
      const res = await startGmailOauthLink({ actorUserId: u, loginHint: email || null }).catch((e) => ({ ok: false, error: String(e) }));
      if (!res.ok) {
        await sendReply(redactText(res.error ?? "oauth-start failed"));
        return { handled: true };
      }
      await sendReply(
        "Open this URL and approve:\n" +
        `${res.auth_url}\n\n` +
        "After approval you may see ERR_CONNECTION_REFUSED. That's fine.\n" +
        "Copy the full redirected URL from the address bar (starts with http://127.0.0.1:PORT/?code=...)\n" +
        "Then DM me:\n" +
        "`email oauth-finish <PASTE_FULL_URL>`"
      );
      return { handled: true };
    }
    if (sub === "oauth-finish") {
      const callbackUrl = cmd.raw.split(/\s+/).slice(2).join(" ").trim();
      if (!callbackUrl) {
        await sendReply("Usage: email oauth-finish <full_redirected_url>");
        return { handled: true };
      }
      const res = await finishGmailOauthLink({ actorUserId: u, callbackUrl }).catch((e) => ({ ok: false, error: String(e) }));
      await sendReply(res.ok ? `Saved OAuth for ${res.email}. Try: \`email inbox\`` : redactText(res.error ?? "oauth-finish failed"));
      return { handled: true };
    }
    if (sub === "clear") {
      const res = await clearUserEmailConfig({ actorUserId: u });
      await sendReply(res.ok ? "Cleared." : redactText(res.error));
      return { handled: true };
    }
    if (sub === "inbox") {
      const limitArg = cmd.parts.find((p) => p.toLowerCase().startsWith("limit="));
      const limit = limitArg ? int(limitArg.split("=", 2)[1]) : 5;
      const res = await runEmail({ actorUserId: u, args: ["inbox", "--limit", String(limit)] }).catch((e) => ({ ok: false, error: String(e) }));
      if (!res.ok) {
        await sendReply(redactText(res.error ?? "email failed"));
        return { handled: true };
      }
      const msgs = Array.isArray(res.messages) ? res.messages : [];
      const lines = msgs.slice(0, 10).map((m) => `- [${m.id}] ${String(m.subject ?? "").slice(0, 120)} (${String(m.from ?? "").slice(0, 60)})`);
      await sendReply(lines.length ? lines.join("\n") : "(empty)");
      return { handled: true };
    }
    if (sub === "read") {
      const id = String(cmd.parts[2] ?? "").trim();
      if (!id) {
        await sendReply("Usage: email read <id>");
        return { handled: true };
      }
      const res = await runEmail({ actorUserId: u, args: ["read", "--id", id] }).catch((e) => ({ ok: false, error: String(e) }));
      if (!res.ok) {
        await sendReply(redactText(res.error ?? "email failed"));
        return { handled: true };
      }
      const text = `From: ${res.from ?? ""}\nSubject: ${res.subject ?? ""}\nDate: ${res.date ?? ""}\n\n${res.snippet ?? ""}\n\n${res.body ? String(res.body).slice(0, 2000) : ""}`;
      await sendReply(redactText(text).slice(0, 3500));
      return { handled: true };
    }
    if (sub === "unread") {
      const limitArg = cmd.parts.find((p) => p.toLowerCase().startsWith("limit="));
      const limit = limitArg ? int(limitArg.split("=", 2)[1]) : 5;
      const res = await runEmail({ actorUserId: u, args: ["unread", "--limit", String(limit)] }).catch((e) => ({ ok: false, error: String(e) }));
      if (!res.ok) {
        await sendReply(redactText(res.error ?? "email failed"));
        return { handled: true };
      }
      const msgs = Array.isArray(res.messages) ? res.messages : [];
      const lines = msgs.slice(0, 10).map((m) => `- [${m.id}] ${String(m.subject ?? "").slice(0, 120)} (${String(m.from ?? "").slice(0, 60)})`);
      await sendReply(lines.length ? lines.join("\n") : "(empty)");
      return { handled: true };
    }
    if (sub === "search") {
      const q = cmd.raw.split(/\s+/).slice(2).join(" ").trim();
      if (!q) {
        await sendReply("Usage: email search <query>");
        return { handled: true };
      }
      const res = await runEmail({ actorUserId: u, args: ["search", "--query", q] }).catch((e) => ({ ok: false, error: String(e) }));
      if (!res.ok) {
        await sendReply(redactText(res.error ?? "email failed"));
        return { handled: true };
      }
      const msgs = Array.isArray(res.messages) ? res.messages : [];
      const lines = msgs.slice(0, 10).map((m) => `- [${m.id}] ${String(m.subject ?? "").slice(0, 120)} (${String(m.from ?? "").slice(0, 60)})`);
      await sendReply(lines.length ? lines.join("\n") : "(empty)");
      return { handled: true };
    }
    if (sub === "send") {
      // Parse key=value pairs from the raw text. Require explicit confirm to reduce accidental sends.
      const raw = cmd.raw;
      const idx = raw.toLowerCase().indexOf("email send");
      const rest = idx >= 0 ? raw.slice(idx + "email send".length).trim() : raw.split(/\s+/).slice(2).join(" ").trim();
      const parts = rest.split(/\s+/).filter(Boolean);

      let to = "";
      let subject = "";
      let body = "";
      let confirm = false;

      for (let i = 0; i < parts.length; i++) {
        const p = parts[i];
        if (p.toLowerCase() === "confirm=yes" || p.toLowerCase() === "--confirm") confirm = true;
        if (p.toLowerCase().startsWith("to=")) to = p.slice(3);
        if (p.toLowerCase().startsWith("subject=")) subject = p.slice(8);
        if (p.toLowerCase().startsWith("body=")) {
          body = parts.slice(i).join(" ").slice(5); // keep spaces; everything after body=
          break;
        }
      }

      if (!to || !body) {
        await sendReply("Usage: email send to=<addr> subject=<text> body=<text> confirm=yes");
        return { handled: true };
      }
      if (!confirm) {
        await sendReply(
          `Send preview:\nTo: ${to}\nSubject: ${subject}\nBody: ${String(body).slice(0, 200)}${String(body).length > 200 ? "..." : ""}\n\n` +
          "To actually send, re-run with `confirm=yes`."
        );
        return { handled: true };
      }

      const res = await runEmail({ actorUserId: u, args: ["send", "--to", to, "--subject", subject, "--body", body] }).catch((e) => ({ ok: false, error: String(e) }));
      if (!res.ok) {
        await sendReply(redactText(res.error ?? "email failed"));
        return { handled: true };
      }
      await sendReply(`Sent. id=${res.id ?? ""}`.trim());
      return { handled: true };
    }
  }

  if (head === "me" && (cmd.parts[1] ?? "").toLowerCase() === "api") {
    const sub = (cmd.parts[2] ?? "").toLowerCase();
    if (sub === "set") {
      const provider = String(cmd.parts[3] ?? "").trim().toLowerCase();
      const apiKey = cmd.raw.split(/\s+/).slice(4).join(" ").trim();
      const res = await setUserApiKey({ actorUserId: u, provider, apiKey });
      await sendReply(res.ok ? "Saved." : redactText(res.error));
      return { handled: true };
    }
    if (sub === "clear") {
      const provider = String(cmd.parts[3] ?? "").trim().toLowerCase();
      const res = await clearUserApiKey({ actorUserId: u, provider });
      await sendReply(res.ok ? "Cleared." : redactText(res.error));
      return { handled: true };
    }
    if (sub === "status") {
      const providers = ["openai", "brave", "anthropic"];
      const statuses = {};
      for (const p of providers) statuses[p] = Boolean(await getUserApiKey({ actorUserId: u, provider: p }));
      await sendReply(redactText(JSON.stringify({ ok: true, api_keys: statuses })));
      return { handled: true };
    }
  }

  if (head === "claude" || head === "anthropic") {
    const sub = (cmd.parts[1] ?? "").toLowerCase();
    if (sub === "model") {
      const model = cmd.raw.split(/\s+/).slice(2).join(" ").trim();
      if (!model) {
        await sendReply("Usage: claude model <model_id>");
        return { handled: true };
      }
      await writeTextFile(anthropicModelPath(u), model);
      await appendEventsLog(u, `[${isoNow()}] claude model set`);
      await sendReply(`Saved. Model=${model}`);
      return { handled: true };
    }
    if (sub === "system") {
      const sys = cmd.raw.split(/\s+/).slice(2).join(" ").trim();
      if (!sys) {
        await sendReply("Usage: claude system <system_prompt>");
        return { handled: true };
      }
      await writeTextFile(anthropicSystemPath(u), sys);
      await appendEventsLog(u, `[${isoNow()}] claude system set`);
      await sendReply("Saved.");
      return { handled: true };
    }
    if (sub === "clear") {
      await fsp.unlink(anthropicModelPath(u)).catch(() => {});
      await fsp.unlink(anthropicSystemPath(u)).catch(() => {});
      await appendEventsLog(u, `[${isoNow()}] claude clear`);
      await sendReply("Cleared.");
      return { handled: true };
    }

    const prompt = cmd.raw.split(/\s+/).slice(1).join(" ").trim();
    if (!prompt) {
      await sendReply(
        "Usage:\n" +
        "- `me api set anthropic <api_key>`\n" +
        "- `claude model <model_id>` (optional)\n" +
        "- `claude <prompt>`"
      );
      return { handled: true };
    }

    const model = (await readTextFile(anthropicModelPath(u))) || "claude-3-opus-20240229";
    const system = (await readTextFile(anthropicSystemPath(u))) || "";
    const res = await runAnthropicChat({ actorUserId: u, prompt, model, system }).catch((e) => ({ ok: false, error: String(e) }));
    if (!res.ok) {
      await sendReply(redactText(res.error ?? "claude failed"));
      return { handled: true };
    }
    const out = String(res.text ?? "").trim() || "(empty)";
    await sendReply(redactText(out).slice(0, 3500));
    return { handled: true };
  }

  // Natural-language email access (DM only):
  // We intentionally keep this deterministic (no model) and read-only.
  const t = String(text ?? "").trim();
  const lower = t.toLowerCase();
  try {
    // read/open message <id>
    const m = lower.match(/\b(?:read|open|show)\b.*\b(\d{1,8})\b/);
    if (m) {
      const id = m[1];
      const res = await runEmail({ actorUserId: u, args: ["read", "--id", id] }).catch((e) => ({ ok: false, error: String(e) }));
      if (!res.ok) {
        await sendReply(redactText(res.error ?? "email failed"));
        return { handled: true };
      }
      const msgText = `From: ${res.from ?? ""}\nSubject: ${res.subject ?? ""}\nDate: ${res.date ?? ""}\n\n${res.snippet ?? ""}\n\n${res.body ? String(res.body).slice(0, 2000) : ""}`;
      await sendReply(redactText(msgText).slice(0, 3500));
      return { handled: true };
    }

    // unread / new
    if (/\bunread\b/.test(lower) || /\bnew\b/.test(lower) && /\bemail\b/.test(lower)) {
      const res = await runEmail({ actorUserId: u, args: ["unread", "--limit", "10"] }).catch((e) => ({ ok: false, error: String(e) }));
      if (!res.ok) {
        await sendReply(redactText(res.error ?? "email failed"));
        return { handled: true };
      }
      const msgs = Array.isArray(res.messages) ? res.messages : [];
      const lines = msgs.slice(0, 10).map((mm) => `- [${mm.id}] ${String(mm.subject ?? "").slice(0, 120)} (${String(mm.from ?? "").slice(0, 60)})`);
      await sendReply(lines.length ? lines.join("\n") : "(empty)");
      return { handled: true };
    }

    // inbox / latest
    if (/\binbox\b/.test(lower) || /\blatest\b/.test(lower) || /\brecent\b/.test(lower)) {
      const res = await runEmail({ actorUserId: u, args: ["inbox", "--limit", "10"] }).catch((e) => ({ ok: false, error: String(e) }));
      if (!res.ok) {
        await sendReply(redactText(res.error ?? "email failed"));
        return { handled: true };
      }
      const msgs = Array.isArray(res.messages) ? res.messages : [];
      const lines = msgs.slice(0, 10).map((mm) => `- [${mm.id}] ${String(mm.subject ?? "").slice(0, 120)} (${String(mm.from ?? "").slice(0, 60)})`);
      await sendReply(lines.length ? lines.join("\n") : "(empty)");
      return { handled: true };
    }

    // find/search/about/from/subject keyword search
    const searchMatch = lower.match(/\b(?:search|find|about|subject|from)\b\s+(.+)$/);
    if (searchMatch) {
      const q = t.slice(searchMatch.index ?? 0).replace(/^\s*(search|find|about|subject|from)\s+/i, "").trim();
      if (q) {
        const res = await runEmail({ actorUserId: u, args: ["search", "--query", q] }).catch((e) => ({ ok: false, error: String(e) }));
        if (!res.ok) {
          await sendReply(redactText(res.error ?? "email failed"));
          return { handled: true };
        }
        const msgs = Array.isArray(res.messages) ? res.messages : [];
        const lines = msgs.slice(0, 10).map((mm) => `- [${mm.id}] ${String(mm.subject ?? "").slice(0, 120)} (${String(mm.from ?? "").slice(0, 60)})`);
        await sendReply(lines.length ? lines.join("\n") : "(empty)");
        return { handled: true };
      }
    }
  } catch (e) {
    await sendReply("Email command failed.");
    return { handled: true };
  }

  return { handled: false };
}

function int(s) {
  const n = Number.parseInt(String(s ?? ""), 10);
  return Number.isFinite(n) ? n : 0;
}
