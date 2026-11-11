import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import type { ChatResult } from "../api/types";
import { fakeClient, renderPage } from "../test-utils";
import { Investigator } from "./Investigator";

const reply = (over: Partial<ChatResult> = {}): ChatResult => ({
  status: "ok", text: "The transaction looks unusual.", withheld_reasons: [], tool_calls: [{ name: "get_transaction_risk", args: {}, error: null }],
  verified_citations: ["txn:T-1"], unverified_citations: [], ...over });

function setup(opts: { role?: "viewer" | "analyst"; chat?: unknown } = {}) {
  const client = fakeClient({ "POST /agent/chat": opts.chat ?? (() => reply()) });
  renderPage(<Investigator />, { client, role: opts.role });
  return client;
}
const ask = async (text: string) => {
  await userEvent.type(screen.getByLabelText(/your question/i), text);
  await userEvent.click(screen.getByRole("button", { name: /^send$/i }));
};

describe("AI Investigator", () => {
  it("sends the whole conversation, always ending with the user's turn, roles and content only", async () => {
    const client = setup();
    await ask("hello");
    await screen.findByText("The transaction looks unusual.");
    await ask("and the account?");
    await waitFor(() => expect(client.calls.filter((c) => c.path === "/agent/chat").length).toBe(2));
    const body = client.calls[1].body as { messages: Record<string, string>[] };
    expect(body.messages).toEqual([
      { role: "user", content: "hello" },
      { role: "assistant", content: "The transaction looks unusual." },
      { role: "user", content: "and the account?" },
    ]);
  });

  it("shows verified citations and flags unverified ones", async () => {
    setup({ chat: () => reply({ unverified_citations: ["acct:GHOST"] }) });
    await ask("hello");
    expect(await screen.findByText("txn:T-1")).toBeInTheDocument();
    expect(screen.getByText("acct:GHOST")).toBeInTheDocument();
    expect(screen.getByText(/not retrieved/i)).toBeInTheDocument();
    expect(screen.getByText(/get_transaction_risk/)).toBeInTheDocument();
  });

  it("a withheld reply is shown as a notice with its reasons", async () => {
    setup({ chat: () => reply({ status: "withheld", text: "WITHHELD-TEXT", withheld_reasons: ["asserted fraud as established"] }) });
    await ask("is it fraud?");
    expect(await screen.findByRole("note")).toHaveTextContent(/withheld/i);
    expect(screen.getByRole("note")).toHaveTextContent(/asserted fraud as established/i);
    expect(screen.queryByText("WITHHELD-TEXT")).toBeNull();
  });

  it("a refused or cut-off reply is explained", async () => {
    setup({ chat: () => reply({ status: "iteration_limit", text: "" }) });
    await ask("everything please");
    expect(await screen.findByRole("note")).toHaveTextContent(/too many steps/i);
  });

  it("503 and 502 show their own messages", async () => {
    const first = setup({ chat: () => { throw new ApiError(503, "no language model is configured for chat"); } });
    await ask("hi");
    expect(await screen.findByText(/no language model is configured/i)).toBeInTheDocument();
    expect(first.calls).toHaveLength(1);
  });

  it("502 says the request failed and can be retried", async () => {
    setup({ chat: () => { throw new ApiError(502, "the language model request failed"); } });
    await ask("hi");
    expect(await screen.findByText(/request failed\. try again/i)).toBeInTheDocument();
  });

  it("viewers see an explanation and no input", async () => {
    setup({ role: "viewer" });
    expect(screen.queryByLabelText(/your question/i)).toBeNull();
    expect(screen.getByText(/analysts and admins/i)).toBeInTheDocument();
  });

  it("renders a reply containing HTML as literal text", async () => {
    const html = "<img src=x onerror=alert(1)>";
    setup({ chat: () => reply({ text: html }) });
    await ask("hi");
    expect(await screen.findByText(html)).toBeInTheDocument();
    expect(document.body.querySelector("img")).toBeNull();
  });

  it("blocks a message over 8000 characters", async () => {
    const client = setup();
    fireEvent.change(screen.getByLabelText(/your question/i), { target: { value: "x".repeat(8001) } });
    await userEvent.click(screen.getByRole("button", { name: /^send$/i }));
    expect(await screen.findByText(/at most 8000/i)).toBeInTheDocument();
    expect(client.calls).toHaveLength(0);
  });

  it("a new conversation clears the history", async () => {
    setup();
    await ask("hello");
    await screen.findByText("The transaction looks unusual.");
    await userEvent.click(screen.getByRole("button", { name: /new conversation/i }));
    expect(screen.queryByText("The transaction looks unusual.")).toBeNull();
  });
});
