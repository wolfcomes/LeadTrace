import type { InjectionKey, Ref } from "vue";

export const previewInstanceKey: InjectionKey<Ref<string | null>> = Symbol("previewInstance");

export async function loadPreviewInstance(): Promise<string | null> {
  try {
    const response = await fetch("/api/preview/environment", { credentials: "same-origin", cache: "no-store" });
    if (!response.ok) return null;
    const metadata = await response.json();
    return metadata.environment === "preview" && typeof metadata.instance_id === "string"
      ? metadata.instance_id : null;
  } catch {
    // Ordinary deployments have no Preview capability endpoint.
    return null;
  }
}
