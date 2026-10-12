// Application entry point: mounts the React App into the #root element of index.html.
// Wraps it in StrictMode (extra development-time checks) and loads the global theme styles.
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./theme.css";

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
