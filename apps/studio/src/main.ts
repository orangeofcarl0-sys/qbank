import "vditor/dist/index.css";
import "./styles.css";
import { FixtureRpcBridge } from "./fixture-bridge";
import { StudioApp } from "./studio-app";

const root = document.querySelector<HTMLElement>("#app");
if (root === null) throw new Error("missing application root");

const fixtureMode = import.meta.env.DEV && new URLSearchParams(window.location.search).has("fixture");
const fixtureBridge = fixtureMode ? new FixtureRpcBridge() : null;
const app = new StudioApp(root, fixtureBridge ?? undefined);
void app.start().then(() => {
  if (fixtureMode) {
    Object.assign(window, {
      __QBANK_STUDIO_TEST__: app,
      __QBANK_STUDIO_FIXTURE__: fixtureBridge,
    });
    return app.openRepository("fixture://synthetic-bank");
  }
});
