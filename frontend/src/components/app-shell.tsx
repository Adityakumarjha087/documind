"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  BarChart3,
  BookOpenCheck,
  FileText,
  FlaskConical,
  LogOut,
  Menu,
  MessageSquare,
  Plus,
  Users,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { api, json } from "@/lib/api";
import { useAuth } from "@/lib/auth-store";
import { canAdmin, useMe, useWorkspaces } from "@/lib/hooks";
import type { Workspace } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ThemeToggle } from "./theme-toggle";
import { Button } from "./ui/button";
import { Select } from "./ui/input";

const NAV = [
  { href: "chat", label: "Chat", icon: MessageSquare, admin: false },
  { href: "documents", label: "Documents", icon: FileText, admin: false },
  { href: "eval", label: "Evaluation", icon: FlaskConical, admin: false },
  { href: "analytics", label: "Analytics", icon: BarChart3, admin: true },
  { href: "members", label: "Members", icon: Users, admin: false },
];

export function AppShell({ workspaceId, children }: { workspaceId: string; children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const qc = useQueryClient();
  const { data: me } = useMe();
  const { data: workspaces } = useWorkspaces();
  const { refreshToken, clear } = useAuth();
  const [open, setOpen] = useState(false);
  const current = workspaces?.find((w) => w.id === workspaceId);

  async function logout() {
    if (refreshToken) {
      await api("/api/auth/logout", { method: "POST", ...json({ refresh_token: refreshToken }) }).catch(() => {});
    }
    clear();
    qc.clear();
    router.replace("/login");
  }

  async function createWorkspace() {
    const name = window.prompt("Workspace name");
    if (!name?.trim()) return;
    try {
      const ws = await api<Workspace>("/api/workspaces", { method: "POST", ...json({ name: name.trim() }) });
      await qc.invalidateQueries({ queryKey: ["workspaces"] });
      router.push(`/w/${ws.id}/documents`);
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  const sidebar = (
    <nav aria-label="Main" className="flex h-full flex-col gap-4 p-4">
      <Link href="/workspaces" className="flex items-center gap-2 font-semibold text-primary">
        <BookOpenCheck className="h-5 w-5" aria-hidden /> DocuMind
      </Link>
      <div className="flex flex-col gap-1">
        <label htmlFor="ws-switch" className="text-xs uppercase tracking-wide text-muted-foreground">
          Workspace
        </label>
        <div className="flex gap-1">
          <Select
            id="ws-switch"
            value={workspaceId}
            onChange={(e) => router.push(`/w/${e.target.value}/chat`)}
          >
            {workspaces?.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </Select>
          <Button variant="outline" size="icon" aria-label="Create workspace" onClick={createWorkspace}>
            <Plus className="h-4 w-4" aria-hidden />
          </Button>
        </div>
        {current && <span className="text-xs text-muted-foreground">Your role: {current.role}</span>}
      </div>
      <ul className="flex flex-col gap-1">
        {NAV.filter((n) => !n.admin || canAdmin(current)).map(({ href, label, icon: Icon }) => {
          const target = `/w/${workspaceId}/${href}`;
          const active = pathname.startsWith(target);
          return (
            <li key={href}>
              <Link
                href={target}
                onClick={() => setOpen(false)}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex items-center gap-2 rounded-md px-3 py-2 text-sm hover:bg-muted",
                  active && "bg-accent font-medium text-primary",
                )}
              >
                <Icon className="h-4 w-4" aria-hidden /> {label}
              </Link>
            </li>
          );
        })}
      </ul>
      <div className="mt-auto flex items-center justify-between gap-2 border-t border-border pt-4">
        <div className="min-w-0 text-sm">
          <p className="truncate font-medium">{me?.full_name}</p>
          <p className="truncate text-xs text-muted-foreground">{me?.email}</p>
        </div>
        <div className="flex">
          <ThemeToggle />
          <Button variant="ghost" size="icon" aria-label="Log out" onClick={logout}>
            <LogOut className="h-4 w-4" aria-hidden />
          </Button>
        </div>
      </div>
    </nav>
  );

  return (
    <div className="flex h-screen">
      <aside className="hidden w-64 shrink-0 border-r border-border bg-card md:block">{sidebar}</aside>
      {open && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} aria-hidden />
          <aside className="absolute left-0 top-0 h-full w-72 bg-card">{sidebar}</aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b border-border p-2 md:hidden">
          <Button variant="ghost" size="icon" aria-label={open ? "Close menu" : "Open menu"} onClick={() => setOpen(!open)}>
            {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </Button>
          <span className="font-semibold">{current?.name ?? "DocuMind"}</span>
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}
