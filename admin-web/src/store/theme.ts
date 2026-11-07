import { useSyncExternalStore } from "react";

export type ThemeMode = "light" | "dark";

const THEME_KEY = "image2:admin-web:theme";
const listeners = new Set<() => void>();

let currentTheme = getInitialTheme();

function getInitialTheme(): ThemeMode {
  const savedTheme = window.localStorage.getItem(THEME_KEY);

  if (savedTheme === "light" || savedTheme === "dark") {
    return savedTheme;
  }

  return "light";
}

function emitThemeChange() {
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot() {
  return currentTheme;
}

export function useThemeMode() {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

export function toggleThemeMode() {
  currentTheme = currentTheme === "light" ? "dark" : "light";
  window.localStorage.setItem(THEME_KEY, currentTheme);
  emitThemeChange();
}
