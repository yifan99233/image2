const ACCESS_TOKEN_KEY = "image2:user-web:access-token";

export const sessionStorageService = {
  getAccessToken() {
    return window.localStorage.getItem(ACCESS_TOKEN_KEY);
  },
  setAccessToken(token: string) {
    window.localStorage.setItem(ACCESS_TOKEN_KEY, token);
  },
  clearAccessToken() {
    window.localStorage.removeItem(ACCESS_TOKEN_KEY);
  },
};
