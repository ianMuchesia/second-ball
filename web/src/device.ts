// Can this device show the 3D pitch? Checked once, without loading three.js:
// 2D stays the default, and phones and slow devices keep it.
let checked: { ok: boolean; why: string } | null = null;

export function can3d(): { ok: boolean; why: string } {
  if (checked) return checked;
  try {
    const nav = navigator as Navigator & { deviceMemory?: number };
    if (window.matchMedia?.("(max-width: 760px)").matches) checked = { ok: false, why: "needs a larger screen" };
    else if ((nav.hardwareConcurrency ?? 8) < 4 || (nav.deviceMemory ?? 8) < 4)
      checked = { ok: false, why: "needs a faster device" };
    // The API exists: enough to offer 3D (making a context here would cost
    // every page load; the 3D pitch reports a failure itself).
    else if (!("WebGL2RenderingContext" in window))
      checked = { ok: false, why: "needs WebGL 2" };
    else checked = { ok: true, why: "" };
  } catch {
    checked = { ok: false, why: "needs WebGL 2" };
  }
  return checked;
}
