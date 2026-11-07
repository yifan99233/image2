import assert from "node:assert/strict";
import { generateKeyPairSync, privateDecrypt, webcrypto } from "node:crypto";
import test from "node:test";

import { encryptPassword } from "./rsa.ts";

const originalWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
test.afterEach(() => {
  if (originalWindow) Object.defineProperty(globalThis, "window", originalWindow);
  else delete globalThis.window;
});

const setWindow = (value) => {
  Object.defineProperty(globalThis, "window", { configurable: true, value });
};

test("HTTP pages without Web Crypto explain how to open a secure login", async () => {
  setWindow({ crypto: {}, isSecureContext: false });
  await assert.rejects(encryptPassword("test-only", "unused"), {
    name: "Error",
    message: "当前页面未使用安全连接，无法加密登录密码，请使用 HTTPS 域名打开",
  });
});

test("secure browsers without Web Crypto get a compatibility message", async () => {
  setWindow({ isSecureContext: true });
  await assert.rejects(encryptPassword("test-only", "unused"), {
    name: "Error",
    message: "当前浏览器不支持安全加密，请使用最新版 Chrome、Edge 或 Safari 浏览器",
  });
});

test("supported secure contexts keep the server-compatible RSA-OAEP encryption", async () => {
  setWindow({ crypto: webcrypto, isSecureContext: true, atob, btoa });
  const { publicKey, privateKey } = generateKeyPairSync("rsa", {
    modulusLength: 2048,
    publicKeyEncoding: { type: "spki", format: "pem" },
    privateKeyEncoding: { type: "pkcs8", format: "pem" },
  });
  const password = "test-password-中文";
  const encrypted = await encryptPassword(password, publicKey);
  const ciphertext = Buffer.from(encrypted, "base64");
  assert.equal(ciphertext.length, 256);
  const decrypted = privateDecrypt({ key: privateKey, oaepHash: "sha256" }, ciphertext);
  assert.equal(decrypted.toString("utf8"), password);
});
