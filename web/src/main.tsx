import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App";
import { AppProvider } from "./store";

const el = document.getElementById("root");
if (!el) throw new Error("#root element is missing in index.html");
const root = createRoot(el);

// dev only: /?replay=<generation id>[&speed=3] plays a finished build again on the build screen (dropped from the
// production bundle: import.meta.env.DEV is false there)
const params = new URLSearchParams(window.location.search);
const replay = import.meta.env.DEV ? params.get("replay") : null;
if (replay) {
  const speed = Number(params.get("speed")) || 3;
  void import("./dev/StageReplay").then(({ default: StageReplay }) =>
    root.render(
      <StrictMode>
        <AppProvider>
          <StageReplay gid={replay} speed={speed} />
        </AppProvider>
      </StrictMode>,
    ),
  );
} else {
  root.render(
    <StrictMode>
      <AppProvider>
        <App />
      </AppProvider>
    </StrictMode>,
  );
}
