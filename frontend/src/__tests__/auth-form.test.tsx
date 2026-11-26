import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AuthForm } from "@/components/auth-form";
import { useAuth } from "@/lib/auth-store";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, push: vi.fn() }) }));
vi.mock("next-themes", () => ({ useTheme: () => ({ resolvedTheme: "light", setTheme: vi.fn() }) }));

describe("AuthForm", () => {
  afterEach(() => vi.restoreAllMocks());

  it("logs in, stores tokens and redirects", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ access_token: "a", refresh_token: "r", token_type: "bearer", expires_in: 900 }), {
        status: 200,
      }),
    );
    render(<AuthForm mode="login" />);
    await userEvent.type(screen.getByLabelText("Email"), "demo@documind.dev");
    await userEvent.type(screen.getByLabelText("Password"), "demo-password-123");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(useAuth.getState().accessToken).toBe("a");
    expect(replace).toHaveBeenCalledWith("/workspaces");
  });

  it("shows the server error message on failure", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ error: { code: "conflict", message: "An account with this email already exists" } }), {
        status: 409,
      }),
    );
    render(<AuthForm mode="register" />);
    await userEvent.type(screen.getByLabelText("Full name"), "Ada");
    await userEvent.type(screen.getByLabelText("Email"), "ada@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "longpassword");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already exists");
  });
});
