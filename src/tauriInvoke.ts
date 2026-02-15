export async function invoke<T>(cmd: string, args?: any): Promise<T> {
  const isTauri = typeof window !== "undefined" && (window as any).__TAURI__ != null;

  if (!isTauri) {
    throw new Error(`Tauri invoke("${cmd}") not available here (browser/iframe).`);
  }

  const mod = await import("@tauri-apps/api/core");
  return mod.invoke<T>(cmd, args);
}
