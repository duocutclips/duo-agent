// Runtime environment: Tauri desktop shell or a plain browser (development / automated UI tests).

export interface BackendConfig {
  url: string;
  token: string;
}

declare global {
  interface Window {
    __TAURI_INTERNALS__?: unknown;
  }
}

export const isTauri = (): boolean => typeof window !== "undefined" && window.__TAURI_INTERNALS__ !== undefined;

let cached: Promise<BackendConfig> | null = null;

export function backendConfig(): Promise<BackendConfig> {
  if (!cached) {
    cached = (async () => {
      if (isTauri()) {
        const { invoke } = await import("@tauri-apps/api/core");
        try {
          return await invoke<BackendConfig>("backend_config");
        } catch (e) {
          cached = null; // allow a retry on the next request
          throw new Error(String(e));
        }
      }
      return {
        url: (import.meta.env.VITE_API_URL as string | undefined) ?? "http://127.0.0.1:8765",
        token: (import.meta.env.VITE_API_TOKEN as string | undefined) ?? "",
      };
    })();
  }
  return cached;
}

export interface PickedFile {
  path?: string; // Tauri: a local path (imported by reference, no copy)
  file?: File; // Browser: an uploaded file
  name: string;
}

/** Native file dialog in Tauri; a hidden <input type=file> in the browser. */
export async function pickFiles(extensions: string[], multiple = true): Promise<PickedFile[]> {
  if (isTauri()) {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const res = await open({ multiple, filters: [{ name: "Supported files", extensions }] });
    if (!res) return [];
    const paths = Array.isArray(res) ? res : [res];
    return paths.map((p) => ({ path: p, name: p.split(/[\\/]/).pop() ?? p }));
  }
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = multiple;
    input.accept = extensions.map((e) => "." + e).join(",");
    input.onchange = () => resolve(Array.from(input.files ?? []).map((f) => ({ file: f, name: f.name })));
    input.click();
  });
}

export async function copyText(text: string): Promise<void> {
  await navigator.clipboard.writeText(text);
}

export function openExternal(url: string): void {
  window.open(url, "_blank", "noopener,noreferrer");
}
