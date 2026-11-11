import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Login } from "./Login";
import { SessionProvider } from "./session";

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

function setup(fetchImpl?: typeof fetch) {
  const f = fetchImpl ?? ((async () => json(401, { detail: "Invalid or missing credentials" })) as unknown as typeof fetch);
  return render(<MemoryRouter><SessionProvider fetchImpl={f}><Login /></SessionProvider></MemoryRouter>);
}
const password = () => screen.getByLabelText(/^password$/i) as HTMLInputElement;
const username = () => screen.getByLabelText(/^username$/i) as HTMLInputElement;

describe("Login page", () => {
  it("has a clear title and subtitle", () => {
    setup();
    expect(screen.getByRole("heading", { level: 1, name: "SENTINEL" })).toBeInTheDocument();
    expect(screen.getByText(/payment-fraud intelligence/i)).toBeInTheDocument();
    expect(screen.getByText(/nothing is blocked automatically/i)).toBeInTheDocument();
  });

  it("labels the fields and asks the browser for the right autofill", () => {
    setup();
    expect(username()).toHaveAttribute("autocomplete", "username");
    expect(password()).toHaveAttribute("autocomplete", "current-password");
  });

  it("shows and hides the password on request", async () => {
    setup();
    expect(password().type).toBe("password");
    await userEvent.click(screen.getByRole("button", { name: /show password/i }));
    expect(password().type).toBe("text");
    await userEvent.click(screen.getByRole("button", { name: /hide password/i }));
    expect(password().type).toBe("password");
  });

  it("demo buttons fill only the username and move to the password box", async () => {
    setup();
    await userEvent.click(screen.getByRole("button", { name: /^ana\b/i }));
    expect(username().value).toBe("ana");
    expect(password().value).toBe("");
    expect(password()).toHaveFocus();
  });

  it("warns when Caps Lock is on while typing the password", () => {
    setup();
    fireEvent.keyDown(password(), { key: "A", modifierCapsLock: true });
    expect(screen.getByText(/caps lock is on/i)).toBeInTheDocument();
  });

  it("shows the server's message and re-enables the button after a failed sign-in", async () => {
    setup();
    await userEvent.type(username(), "ana");
    await userEvent.type(password(), "wrong");
    await userEvent.click(screen.getByRole("button", { name: /^sign in$/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid or missing credentials");
    await waitFor(() => expect(screen.getByRole("button", { name: /^sign in$/i })).toBeEnabled());
  });

  it("disables the button and says so while signing in", async () => {
    let release!: () => void;
    const slow = (() => new Promise<Response>((r) => { release = () => r(json(401, { detail: "no" })); })) as unknown as typeof fetch;
    setup(slow);
    await userEvent.type(username(), "ana");
    await userEvent.type(password(), "pw");
    await userEvent.click(screen.getByRole("button", { name: /^sign in$/i }));
    expect(await screen.findByRole("button", { name: /signing in/i })).toBeDisabled();
    release();
  });
});
