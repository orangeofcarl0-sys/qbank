import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe("Tauri capability boundary", () => {
  it("permits only the bundled sidecar and no arguments", () => {
    const capability = JSON.parse(readFileSync("src-tauri/capabilities/default.json", "utf8")) as {
      permissions: Array<string | { identifier: string; allow: Array<{ name: string; sidecar: boolean; args: boolean }> }>;
    };
    const scoped = capability.permissions.filter((item) => typeof item !== "string");
    expect(scoped).toHaveLength(3);
    for (const permission of scoped) {
      expect(permission.allow).toEqual([
        { name: "binaries/qbank-sidecar", sidecar: true, args: false },
      ]);
    }
    expect(JSON.stringify(capability)).not.toContain("shell:allow-execute");
    expect(JSON.stringify(capability)).not.toContain("fs:");
    expect(JSON.stringify(capability)).not.toContain("opener:");
    expect(capability.permissions).toContain("dialog:allow-open");
    expect(capability.permissions).toContain("dialog:allow-message");
  });

  it("uses a non-null CSP without remote origins", () => {
    const config = JSON.parse(readFileSync("src-tauri/tauri.conf.json", "utf8")) as {
      app: { security: { csp: string } };
    };
    expect(config.app.security.csp).toContain("default-src 'self'");
    expect(config.app.security.csp).not.toMatch(/https:/);
    const scriptDirective = config.app.security.csp.split(";").find((value) => value.trim().startsWith("script-src"));
    expect(scriptDirective).not.toContain("'unsafe-eval'");
    expect(scriptDirective).not.toContain("'unsafe-inline'");
    expect(scriptDirective).toContain("sha256-qR4U4J3Ne5n0m3uNzGMB/tZ3TWJUf89OlxdXqjqALDM=");
  });

  it("isolates preview content in a scriptless sandboxed frame", () => {
    const source = readFileSync("src/secure-preview.ts", "utf8");
    expect(source).toContain('setAttribute("sandbox", "allow-same-origin")');
    expect(source).toContain("script-src 'none'");
    expect(source).toContain("connect-src 'none'");
  });

  it("bundles only the fixed sidecar with a current-user NSIS installer", () => {
    const config = JSON.parse(readFileSync("src-tauri/tauri.conf.json", "utf8")) as {
      bundle: {
        externalBin: string[];
        targets: string[];
        windows: { nsis: { installMode: string } };
      };
    };
    expect(config.bundle.externalBin).toEqual(["binaries/qbank-sidecar"]);
    expect(config.bundle.targets).toEqual(["nsis"]);
    expect(config.bundle.windows.nsis.installMode).toBe("currentUser");
  });
});
