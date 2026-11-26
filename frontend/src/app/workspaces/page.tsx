"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { RequireAuth } from "@/components/require-auth";
import { ErrorState, Spinner } from "@/components/ui/feedback";
import { useWorkspaces } from "@/lib/hooks";

function Redirector() {
  const router = useRouter();
  const { data, error, refetch } = useWorkspaces();
  useEffect(() => {
    const first = data?.[0];
    if (first) router.replace(`/w/${first.id}/chat`);
  }, [data, router]);
  if (error) return <ErrorState message={error.message} onRetry={() => refetch()} />;
  return <Spinner label="Opening your workspace" />;
}

export default function WorkspacesPage() {
  return (
    <RequireAuth>
      <div className="flex min-h-screen items-center justify-center">
        <Redirector />
      </div>
    </RequireAuth>
  );
}
