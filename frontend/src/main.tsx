import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "@fontsource-variable/inter";
import "@fontsource-variable/source-serif-4";
import "./theme.css";

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
