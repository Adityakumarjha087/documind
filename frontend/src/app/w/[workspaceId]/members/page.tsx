"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { UserMinus, UserPlus } from "lucide-react";
import { useRouter } from "next/navigation";
import { use, useState } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState, Skeleton } from "@/components/ui/feedback";
import { Input, Label, Select } from "@/components/ui/input";
import { api, json } from "@/lib/api";
import { canAdmin, useMe, useWorkspace } from "@/lib/hooks";
import type { Member, Role } from "@/lib/types";

export default function MembersPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const base = `/api/workspaces/${workspaceId}/members`;
  const qc = useQueryClient();
  const router = useRouter();
  const { data: me } = useMe();
  const { data: ws } = useWorkspace(workspaceId);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");
  const admin = canAdmin(ws);

  const members = useQuery({ queryKey: ["members", workspaceId], queryFn: () => api<Member[]>(base) });
  const refresh = () => qc.invalidateQueries({ queryKey: ["members", workspaceId] });

  const add = useMutation({
    mutationFn: () => api(base, { method: "POST", ...json({ email, role }) }),
    onSuccess: () => {
      setEmail("");
      toast.success("Member added");
      refresh();
    },
    onError: (e) => toast.error(e.message),
  });
  const update = useMutation({
    mutationFn: ({ id, role }: { id: string; role: Role }) =>
      api(`${base}/${id}`, { method: "PATCH", ...json({ role }) }),
    onSuccess: refresh,
    onError: (e) => toast.error(e.message),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`${base}/${id}`, { method: "DELETE" }),
    onSuccess: (_, id) => {
      if (id === me?.id) {
        qc.invalidateQueries({ queryKey: ["workspaces"] });
        router.replace("/workspaces");
      } else refresh();
    },
    onError: (e) => toast.error(e.message),
  });

  return (
    <div>
      <PageHeader title="Members" description="Roles: owners manage everything, admins manage members and evaluations." />
      <div className="flex flex-col gap-4 p-6">
        {admin && (
          <Card>
            <CardHeader>
              <CardTitle>Add a member</CardTitle>
            </CardHeader>
            <CardContent>
              <form
                className="flex flex-wrap items-end gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  add.mutate();
                }}
              >
                <div className="flex min-w-64 flex-1 flex-col gap-1">
                  <Label htmlFor="member-email">Email of a registered user</Label>
                  <Input id="member-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
                </div>
                <div className="flex flex-col gap-1">
                  <Label htmlFor="member-role">Role</Label>
                  <Select id="member-role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
                    <option value="member">Member</option>
                    <option value="admin">Admin</option>
                    {ws?.role === "owner" && <option value="owner">Owner</option>}
                  </Select>
                </div>
                <Button type="submit" disabled={add.isPending}>
                  <UserPlus className="h-4 w-4" aria-hidden /> Add
                </Button>
              </form>
            </CardContent>
          </Card>
        )}
        {members.isLoading ? (
          <Skeleton className="h-40" />
        ) : members.error ? (
          <ErrorState message={members.error.message} onRetry={() => members.refetch()} />
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border bg-card">
            <table className="w-full text-sm">
              <thead className="border-b border-border text-left text-muted-foreground">
                <tr>
                  <th className="p-3 font-medium">Name</th>
                  <th className="p-3 font-medium">Email</th>
                  <th className="p-3 font-medium">Role</th>
                  <th className="p-3">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {members.data?.map((m) => (
                  <tr key={m.user_id} className="border-b border-border last:border-0">
                    <td className="p-3 font-medium">
                      {m.full_name} {m.user_id === me?.id && <span className="text-muted-foreground">(you)</span>}
                    </td>
                    <td className="p-3">{m.email}</td>
                    <td className="p-3">
                      {admin ? (
                        <Select
                          aria-label={`Role for ${m.full_name}`}
                          value={m.role}
                          className="w-32"
                          onChange={(e) => update.mutate({ id: m.user_id, role: e.target.value as Role })}
                        >
                          <option value="member">Member</option>
                          <option value="admin">Admin</option>
                          <option value="owner" disabled={ws?.role !== "owner"}>
                            Owner
                          </option>
                        </Select>
                      ) : (
                        <span className="capitalize">{m.role}</span>
                      )}
                    </td>
                    <td className="p-3 text-right">
                      {(admin || m.user_id === me?.id) && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() =>
                            window.confirm(m.user_id === me?.id ? "Leave this workspace?" : `Remove ${m.full_name}?`) &&
                            remove.mutate(m.user_id)
                          }
                        >
                          <UserMinus className="h-4 w-4" aria-hidden /> {m.user_id === me?.id ? "Leave" : "Remove"}
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
