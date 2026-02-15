export function extractReadFileBody(readOut: string): string {
  const endMarker = "\n===== end file =====";
  const end = readOut.lastIndexOf(endMarker);
  if (end < 0) return readOut;

  const firstNl = readOut.indexOf("\n");
  if (firstNl < 0) return readOut;

  return readOut.slice(firstNl + 1, end);
}
