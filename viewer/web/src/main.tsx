import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { initToken } from "./api";
import App from "./App";
import { applyStoredTheme } from "./theme";
import "./styles.css";

initToken();
applyStoredTheme(); // before the first render: no white flash in dark mode

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
