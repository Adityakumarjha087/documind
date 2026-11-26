"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import type { User, Workspace } from "./types";

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: () => api<User>("/api/auth/me") });
}

export function useWorkspaces() {
  return useQuery({ queryKey: ["workspaces"], queryFn: () => api<Workspace[]>("/api/workspaces") });
}

export function useWorkspace(id: string) {
  return useQuery({ queryKey: ["workspace", id], queryFn: () => api<Workspace>(`/api/workspaces/${id}`) });
}

export const canAdmin = (ws?: Workspace) => ws?.role === "owner" || ws?.role === "admin";
