import { Suspense } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { ConnectionProvider } from "./connection/ConnectionProvider.jsx";
import "./index.css";

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("Artifact root element is missing.");

createRoot(rootEl).render(
  <Suspense fallback={null}>
    <ConnectionProvider>
      <App />
    </ConnectionProvider>
  </Suspense>
);
