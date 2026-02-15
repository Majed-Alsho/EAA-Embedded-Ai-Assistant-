const END_MARKER = "\n===== end file =====";

export function extractReadFileBody(readOut: string): string {
  const end = readOut.lastIndexOf(END_MARKER);
  if (end < 0) return readOut;

  const firstNl = readOut.indexOf("\n");
  if (firstNl < 0) return readOut;

  return readOut.slice(firstNl + 1, end);
}

export function splitReadOut(readOut: string) {
  const hasMarkers = readOut.includes(END_MARKER);
  if (!hasMarkers) return { header: "", body: readOut };

  const firstNl = readOut.indexOf("\n");
  const header = firstNl >= 0 ? readOut.slice(0, firstNl) : "";
  const body = extractReadFileBody(readOut);
  return { header, body };
}
