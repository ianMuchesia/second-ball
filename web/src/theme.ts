// Broadcast identity: team codes and kit colours from the Msodoki palette
// (night theme): home in brand amber, away in ivory.
export const KIT = {
  home: { fill: "var(--home)", text: "var(--on-home)" },
  away: { fill: "var(--away)", text: "var(--on-away)" },
};

export function teamCode(name: string): string {
  return name.replace(/[^A-Za-z]/g, "").slice(0, 3).toUpperCase();
}
