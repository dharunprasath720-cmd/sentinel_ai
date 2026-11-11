import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { fakeClient, renderPage } from "../test-utils";
import { Shell } from "./Shell";

function Where() { return <div data-testid="where">{useLocation().pathname}</div>; }
function setup() {
  renderPage(
    <Routes><Route element={<Shell />}><Route path="*" element={<Where />} /></Route></Routes>,
    { client: fakeClient({}) });
}
const open = () => userEvent.keyboard("{Control>}k{/Control}");

describe("command palette", () => {
  it("opens with Ctrl+K, focuses the search box, and closes with Escape", async () => {
    setup();
    expect(screen.queryByRole("dialog", { name: /command palette/i })).toBeNull();
    await open();
    expect(await screen.findByRole("dialog", { name: /command palette/i })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: /search/i })).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: /command palette/i })).toBeNull();
  });

  it("also opens from the header button", async () => {
    setup();
    await userEvent.click(screen.getByRole("button", { name: /search or jump to/i }));
    expect(await screen.findByRole("dialog", { name: /command palette/i })).toBeInTheDocument();
  });

  it("filters pages as you type and Enter jumps to the first match", async () => {
    setup();
    await open();
    await userEvent.type(await screen.findByRole("combobox", { name: /search pages/i }), "graph");
    const list = screen.getByRole("listbox");
    expect(within(list).getByRole("option", { name: /graph explorer/i })).toBeInTheDocument();
    expect(within(list).queryByRole("option", { name: /overview/i })).toBeNull();
    await userEvent.keyboard("{Enter}");
    expect(screen.getByTestId("where")).toHaveTextContent("/graph");
    expect(screen.queryByRole("dialog", { name: /command palette/i })).toBeNull();
  });

  it("offers to open a transaction by id", async () => {
    setup();
    await open();
    await userEvent.type(await screen.findByRole("combobox", { name: /search pages/i }), "SYN0002698");
    expect(screen.getByRole("option", { name: /open investigation for SYN0002698/i })).toBeInTheDocument();
    await userEvent.keyboard("{Enter}");
    expect(screen.getByTestId("where")).toHaveTextContent("/investigation/SYN0002698");
  });

  it("moves the selection with the arrow keys", async () => {
    setup();
    await open();
    await screen.findByRole("combobox", { name: /search pages/i });
    await userEvent.keyboard("{ArrowDown}{Enter}");
    expect(screen.getByTestId("where")).toHaveTextContent("/live"); // second page in the list
  });

  it("says when nothing matches", async () => {
    setup();
    await open();
    await userEvent.type(await screen.findByRole("combobox", { name: /search pages/i }), "zz");
    expect(screen.getByText(/no matches/i)).toBeInTheDocument();
  });
});
