"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { TokenPair } from "./types";

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  setTokens: (t: TokenPair) => void;
  clear: () => void;
}

export const useAuth = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      setTokens: (t) => set({ accessToken: t.access_token, refreshToken: t.refresh_token }),
      clear: () => set({ accessToken: null, refreshToken: null }),
    }),
    { name: "documind-auth" },
  ),
);
