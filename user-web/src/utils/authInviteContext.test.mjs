import assert from "node:assert/strict";
import test from "node:test";
import { URLSearchParams } from "node:url";

import { authPathWithInviteContext, searchWithoutInviteCode } from "./authInviteContext.ts";

test("removes the reward invite code while preserving unrelated query parameters", () => {
  const searchParams = new URLSearchParams("invite_code=U42&campaign=summer");

  assert.equal(searchWithoutInviteCode(searchParams), "campaign=summer");
  assert.equal(searchParams.get("invite_code"), "U42");
});

test("keeps team invite context when removing the reward invite code", () => {
  const searchParams = new URLSearchParams("team_invite_token=team-token&invite_code=U42");

  assert.equal(searchWithoutInviteCode(searchParams), "team_invite_token=team-token");
});

test("builds auth links using only supported invite context", () => {
  const searchParams = new URLSearchParams("team_invite_token=team-token&campaign=summer");

  assert.equal(authPathWithInviteContext("/login", searchParams), "/login?team_invite_token=team-token");
});
