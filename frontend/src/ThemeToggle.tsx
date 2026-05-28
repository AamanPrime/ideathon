import { useCallback, useEffect, useState } from "react";

// Bumped storage key so old "dark" preferences from previous builds are
// ignored — light theme becomes the default for everyone on first load.
const THEME_KEY = "fd-theme-v2";

function getStoredTheme(): "light" | "dark" {
  const stored = localStorage.getItem(THEME_KEY);
  if (stored === "dark" || stored === "light") return stored;
  return "light";
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<"light" | "dark">(getStoredTheme);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((prev) => (prev === "light" ? "dark" : "light"));
  }, []);

  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={toggle}
      aria-label={`Switch to ${theme === "light" ? "dark" : "light"} mode`}
      title={`Switch to ${theme === "light" ? "dark" : "light"} mode`}
    >
      {theme === "light" ? "☾" : "☀"}
    </button>
  );
}
