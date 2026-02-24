import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";

// NOTE: runtime.mjs reads some env vars at module load time.
// Use dynamic import so tests can set env first.
process.env.CLAUDECODE_BOT_USER_ID ||= "999";

const {
  TENANCY_ROOT,
  USERS_ROOT,
  GLOBAL_ROOT,
  ADMIN_USER_ID,
  redactText,
  writeGuard,
  readGuard,
  handleMentionCommand,
  ensureStarted,
  syncNow
} = await import("./runtime.mjs");

function mkFakeDiscordApi() {
  const guildA = "1470210055277121566";
  const chanA = "1470210056086618194";
  const guildB = "1402227387005141154";
  const chanB = "1470566790710169661";

  // permissions: VIEW_CHANNEL for everyone, deny none
  const roles = (guildId) => [
    { id: guildId, permissions: String(1n << 10n) } // @everyone has VIEW_CHANNEL
  ];

  const members = new Map();
  // admin + two users exist in both guilds
  members.set(`${guildA}:${ADMIN_USER_ID}`, { roles: [] });
  members.set(`${guildA}:111`, { roles: [] });
  members.set(`${guildA}:222`, { roles: [] });
  members.set(`${guildB}:${ADMIN_USER_ID}`, { roles: [] });
  members.set(`${guildB}:111`, { roles: [] });
  members.set(`${guildB}:222`, { roles: [] });

  const channels = new Map();
  channels.set(chanA, { id: chanA, guild_id: guildA, permission_overwrites: [] });
  channels.set(chanB, { id: chanB, guild_id: guildB, permission_overwrites: [] });

  return {
    fetchChannel: async (channelId) => {
      const ch = channels.get(String(channelId));
      if (!ch) throw new Error("no channel");
      return ch;
    },
    fetchRoles: async (guildId) => roles(String(guildId)),
    fetchMember: async (guildId, userId) => {
      const key = `${String(guildId)}:${String(userId)}`;
      const m = members.get(key);
      if (!m) throw new Error("no member");
      return m;
    },
    fetchRecentMessages: async (channelId, limit) => {
      const cid = String(channelId);
      const msgs = [];
      // Seed candidates: user 111 in chanA, user 222 in chanB
      if (cid === chanA) msgs.push({ author: { id: "111" } });
      if (cid === chanB) msgs.push({ author: { id: "222" } });
      return msgs.slice(0, limit);
    }
  };
}

async function fileExists(p) {
  try {
    await fs.stat(p);
    return true;
  } catch {
    return false;
  }
}

async function main() {
  // 1) Redaction sanity
  const red = redactText("token=abc sk-1234567890abcdef AKIA1234567890ABCD12 ghp_12345678901234567890");
  assert(!red.includes("sk-1234567890abcdef"));
  assert(!red.includes("ghp_12345678901234567890"));

  // 2) Guards
  {
    const nonAdmin = "111";
    const ownPath = path.join(USERS_ROOT, nonAdmin, "sub-soul.md");
    const otherPath = path.join(USERS_ROOT, "222", "sub-soul.md");
    const otherSecretPath = path.join(USERS_ROOT, "222", "secrets", "openai_api_key");
    const globalPath = path.join(GLOBAL_ROOT, "README.md");
    const outsidePath = "/etc/hosts";

    assert.equal((await writeGuard({ actorUserId: nonAdmin, absPath: ownPath })).ok, true);
    assert.equal((await writeGuard({ actorUserId: nonAdmin, absPath: otherPath })).ok, false);
    assert.equal((await writeGuard({ actorUserId: nonAdmin, absPath: outsidePath })).ok, false);
    assert.equal((await writeGuard({ actorUserId: ADMIN_USER_ID, absPath: outsidePath })).ok, true);

    // Non-admin global read denied by default policy
    const rg = await readGuard({ actorUserId: nonAdmin, absPath: globalPath, content: "ok" });
    assert.equal(rg.ok, false);

    // Non-admin outside tenancy denied
    const ro = await readGuard({ actorUserId: nonAdmin, absPath: outsidePath, content: "ok" });
    assert.equal(ro.ok, false);

    // Redaction on read when secrets exist
    const rr = await readGuard({ actorUserId: nonAdmin, absPath: ownPath, content: "sk-THIS_IS_FAKE\nhello\n" });
    assert.equal(rr.ok, true);
    assert(rr.content.includes("sk-REDACTED"));

    // Non-admin cannot read other user's secrets folder.
    const rs = await readGuard({ actorUserId: nonAdmin, absPath: otherSecretPath, content: "sk-FAKE" });
    assert.equal(rs.ok, false);
  }

  // 3) Dry-run sync: eligible users create folders + allowlists updated
  await ensureStarted({ api: mkFakeDiscordApi() });
  const res = await syncNow();
  assert.equal(res.ok, true);

  // user 111 folder should exist (from chanA)
  assert.equal(await fileExists(path.join(USERS_ROOT, "111", "sub-soul.md")), true);
  assert.equal(await fileExists(path.join(USERS_ROOT, "111", "events.log")), true);
  assert.equal(await fileExists(path.join(USERS_ROOT, "111", "profile.json")), true);

  // user 222 folder should exist (from chanB)
  assert.equal(await fileExists(path.join(USERS_ROOT, "222", "sub-soul.md")), true);

  // 4) Delegation: coding-ish text should call ClaudeCode (worker bot)
  {
    process.env.CLAUDECODE_BOT_USER_ID = "999";
    let last = "";
    const r1 = await handleMentionCommand({
      guildId: "1470210055277121566",
      channelId: "1470210056086618194",
      actorUserId: "111",
      text: "Fix build error: npm test fails in src/index.js",
      sendReply: async (msg) => {
        last = String(msg);
      }
    });
    assert.equal(r1.handled, true);
    assert(last.includes("<@999>"));
    assert(last.includes("mode:CALL"));
    assert(last.includes("owner:OpenClaw"));

    last = "";
    const r2 = await handleMentionCommand({
      guildId: "1470210055277121566",
      channelId: "1470210056086618194",
      actorUserId: "111",
      text: "hello there",
      sendReply: async (msg) => {
        last = String(msg);
      }
    });
    // Non-coding chat should fall through to normal LLM path.
    assert.equal(r2.handled, false);
    assert.equal(last, "");
  }

  console.log("tenancy dry-run: OK");
}

main().catch((err) => {
  console.error(String(err));
  process.exit(1);
});
