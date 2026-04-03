/**
 * Keyboard shortcuts hook — power-user navigation.
 *
 * Global shortcuts work everywhere. Page shortcuts are registered
 * per-page and cleaned up on unmount.
 */

import { useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";

type ShortcutHandler = () => void;

const GLOBAL_SHORTCUTS: Record<string, { path?: string; handler?: string }> = {
  "g d": { path: "/dashboard" },
  "g r": { path: "/runs" },
  "g t": { path: "/tasks" },
  "g q": { path: "/requests" },
  "g a": { path: "/analytics" },
  "g s": { path: "/settings" },
  "g m": { path: "/manage" },
};

/**
 * Global keyboard shortcuts — navigation via g+key chords.
 *
 * g d → Dashboard
 * g r → Runs
 * g t → Tasks
 * g q → Requests (queries)
 * g a → Analytics
 * g s → Settings
 * g m → Manage
 * / → Focus search
 * Escape → Close modal/panel
 */
export function useGlobalKeyboard() {
  const navigate = useNavigate();

  useEffect(() => {
    let pendingG = false;
    let gTimeout: number | undefined;

    const handler = (e: KeyboardEvent) => {
      // Don't capture when typing in inputs
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
        // Only handle Escape in inputs
        if (e.key === "Escape") {
          (e.target as HTMLElement).blur();
        }
        return;
      }

      // / → Focus search input
      if (e.key === "/" && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        const search = document.querySelector<HTMLInputElement>(
          ".runs-search, .search-input, .create-bar-input"
        );
        if (search) search.focus();
        return;
      }

      // Escape → Close any open panel/modal
      if (e.key === "Escape") {
        // Dispatch custom event for components to handle
        document.dispatchEvent(new CustomEvent("entourage:escape"));
        return;
      }

      // Cmd+K or Ctrl+K → Command palette (future)
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        document.dispatchEvent(new CustomEvent("entourage:command-palette"));
        return;
      }

      // g + key chord for navigation
      if (e.key === "g" && !pendingG) {
        pendingG = true;
        gTimeout = window.setTimeout(() => {
          pendingG = false;
        }, 500);
        return;
      }

      if (pendingG) {
        pendingG = false;
        clearTimeout(gTimeout);

        const combo = `g ${e.key}`;
        const shortcut = GLOBAL_SHORTCUTS[combo];
        if (shortcut?.path) {
          e.preventDefault();
          navigate(shortcut.path);
        }
      }
    };

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [navigate]);
}

/**
 * Page-level keyboard shortcuts.
 *
 * Usage:
 *   usePageKeyboard({
 *     "j": () => selectNext(),
 *     "k": () => selectPrev(),
 *     "Enter": () => approveSelected(),
 *   });
 */
export function usePageKeyboard(shortcuts: Record<string, ShortcutHandler>) {
  const handler = useCallback(
    (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

      const fn = shortcuts[e.key];
      if (fn) {
        e.preventDefault();
        fn();
      }
    },
    [shortcuts]
  );

  useEffect(() => {
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [handler]);
}

/**
 * Listen for Escape key events dispatched by useGlobalKeyboard.
 */
export function useEscapeKey(callback: () => void) {
  useEffect(() => {
    const handler = () => callback();
    document.addEventListener("entourage:escape", handler);
    return () => document.removeEventListener("entourage:escape", handler);
  }, [callback]);
}
