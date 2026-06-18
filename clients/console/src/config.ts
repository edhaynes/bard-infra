// Console runtime configuration — env-driven, validated up front.
// Shared rules §2 (no hardcoded endpoints; one config layer) and §0.11
// (fail fast and loudly — a missing API base URL renders an error screen,
// it never silently falls back to sample data).

export type ConsoleMode = 'api' | 'sample';

export interface ConsoleConfig {
  mode: ConsoleMode;
  /** Registry control-plane base URL, e.g. http://registry.tailnet:8081 */
  apiBaseUrl: string | null;
  /** Bearer token for the read-only console (dev posture; see README). */
  apiToken: string | null;
  /** Non-empty = configuration is invalid; the App renders these verbatim. */
  errors: string[];
}

/** Pure so it is testable; the entrypoint passes `import.meta.env`. */
export function loadConfig(env: Record<string, string | undefined>): ConsoleConfig {
  const apiBaseUrl = env.VITE_API_BASE_URL || null;
  const apiToken = env.VITE_API_TOKEN || null;

  // Sample data is an EXPLICIT dev flag, never a fallback (§0.11).
  if (env.VITE_USE_SAMPLE_DATA === 'true') {
    return { mode: 'sample', apiBaseUrl, apiToken, errors: [] };
  }

  const errors: string[] = [];
  if (!apiBaseUrl) {
    errors.push(
      'VITE_API_BASE_URL is not set. Point it at your Registry ' +
        '(see .env.example), or set VITE_USE_SAMPLE_DATA=true for a demo with sample data.',
    );
  }
  if (!apiToken) {
    errors.push('VITE_API_TOKEN is not set. The console needs a token to read your device list.');
  }
  return { mode: 'api', apiBaseUrl, apiToken, errors };
}
