const pemToArrayBuffer = (pem: string) => {
  const base64 = pem
    .replace(/-----BEGIN PUBLIC KEY-----/g, "")
    .replace(/-----END PUBLIC KEY-----/g, "")
    .replace(/\s/g, "");
  const binary = window.atob(base64);
  const bytes = new Uint8Array(binary.length);

  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }

  return bytes.buffer;
};

export const encryptPassword = async (password: string, publicKey: string) => {
  const subtle = window.crypto?.subtle;
  if (!subtle) {
    if (!window.isSecureContext) {
      throw new Error("当前页面未使用安全连接，无法加密登录密码，请使用 HTTPS 域名打开");
    }
    throw new Error("当前浏览器不支持安全加密，请使用最新版 Chrome、Edge 或 Safari 浏览器");
  }

  const key = await subtle.importKey(
    "spki",
    pemToArrayBuffer(publicKey),
    { name: "RSA-OAEP", hash: "SHA-256" },
    false,
    ["encrypt"],
  );

  const encrypted = await subtle.encrypt(
    { name: "RSA-OAEP" },
    key,
    new TextEncoder().encode(password),
  );

  const encryptedBytes = new Uint8Array(encrypted);
  let binary = "";
  encryptedBytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });

  return window.btoa(binary);
};
