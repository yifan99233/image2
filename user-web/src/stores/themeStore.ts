import { create } from "zustand";

type ThemeMode = "light" | "dark";

type ThemeStore = {
  themeMode: ThemeMode;
  toggleTheme: () => void;
};

const THEME_KEY = "image2:user-web:theme";

const getInitialTheme = (): ThemeMode => {
  const savedTheme = window.localStorage.getItem(THEME_KEY);

  if (savedTheme === "light" || savedTheme === "dark") {
    return savedTheme;
  }

  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
};

export const useThemeStore = create<ThemeStore>((set, get) => ({
  themeMode: getInitialTheme(),
  toggleTheme() {
    const nextTheme = get().themeMode === "light" ? "dark" : "light";
    window.localStorage.setItem(THEME_KEY, nextTheme);
    set({ themeMode: nextTheme });
  },
}));
