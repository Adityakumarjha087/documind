"use client";

import { BookOpenCheck } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ApiError, api, json } from "@/lib/api";
import { useAuth } from "@/lib/auth-store";
import type { TokenPair } from "@/lib/types";
import { ThemeToggle } from "./theme-toggle";
import { Button } from "./ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { Input, Label } from "./ui/input";

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const setTokens = useAuth((s) => s.setTokens);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const isRegister = mode === "register";

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const body = Object.fromEntries(form.entries());
    setPending(true);
    setError(null);
    try {
      const tokens = await api<TokenPair>(`/api/auth/${mode}`, { method: "POST", ...json(body) });
      setTokens(tokens);
      router.replace("/workspaces");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the server");
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <div className="absolute right-4 top-4">
        <ThemeToggle />
      </div>
      <Card className="w-full max-w-sm">
        <CardHeader>
          <div className="mb-2 flex items-center gap-2 text-primary">
            <BookOpenCheck className="h-6 w-6" aria-hidden />
            <span className="text-lg font-semibold">DocuMind</span>
          </div>
          <CardTitle>{isRegister ? "Create your account" : "Sign in"}</CardTitle>
          <CardDescription>
            {isRegister ? "A private workspace is created for you." : "Chat with your team's documents."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="flex flex-col gap-3" noValidate={false}>
            {isRegister && (
              <div className="flex flex-col gap-1">
                <Label htmlFor="full_name">Full name</Label>
                <Input id="full_name" name="full_name" required autoComplete="name" />
              </div>
            )}
            <div className="flex flex-col gap-1">
              <Label htmlFor="email">Email</Label>
              <Input id="email" name="email" type="email" required autoComplete="email" />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                name="password"
                type="password"
                required
                minLength={8}
                autoComplete={isRegister ? "new-password" : "current-password"}
              />
            </div>
            {error && (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            )}
            <Button type="submit" disabled={pending}>
              {pending ? "Please wait…" : isRegister ? "Create account" : "Sign in"}
            </Button>
          </form>
          <p className="mt-4 text-center text-sm text-muted-foreground">
            {isRegister ? "Already have an account? " : "New to DocuMind? "}
            <Link className="text-primary underline-offset-4 hover:underline" href={isRegister ? "/login" : "/register"}>
              {isRegister ? "Sign in" : "Create an account"}
            </Link>
          </p>
          {!isRegister && (
            <p className="mt-2 text-center text-xs text-muted-foreground">
              Demo: demo@documind.dev / demo-password-123
            </p>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
