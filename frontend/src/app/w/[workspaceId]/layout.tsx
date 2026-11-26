"use client";

import { use } from "react";
import { AppShell } from "@/components/app-shell";
import { RequireAuth } from "@/components/require-auth";

export default function WorkspaceLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = use(params);
  return (
    <RequireAuth>
      <AppShell workspaceId={workspaceId}>{children}</AppShell>
    </RequireAuth>
  );
}
