/** {{contact.name}}-style variables, substituted client-side at insert time so
 * the agent sees (and can edit) real values. Unresolved keys stay literal
 * (Chatwoot rule — the agent notices and fixes them before sending). */
export function substituteVariables(
  content: string,
  vars: Record<string, string | null | undefined>,
): string {
  return content.replace(/\{\{\s*([a-zA-Z._]+)\s*\}\}/g, (match, key: string) => {
    const value = vars[key.toLowerCase()];
    return value ?? match;
  });
}
