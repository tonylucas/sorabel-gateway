import { CopilotRuntime, createCopilotEndpoint } from "@copilotkit/runtime/v2";
import { BuiltInAgent } from "@copilotkit/runtime/v2";

const MCP_URL = process.env.MCP_URL ?? "http://127.0.0.1:8000/mcp";
const MODEL = process.env.GEMINI_MODEL ?? "google/gemini-2.5-flash";
const PROFILES = ["support", "commercial", "dev"];
const PROFILE_HEADER = "x-sorabel-profile";

/** Le profil est déclaré par le client, jamais deviné : header, sinon `support`. */
function resolveProfile(request: Request): string {
  const declared = (request.headers.get(PROFILE_HEADER) ?? "").trim().toLowerCase();
  return PROFILES.includes(declared) ? declared : "support";
}

/**
 * `options.fetch` est le point d'extension documenté du transport Streamable
 * HTTP : c'est par lui que le profil traverse le client MCP jusqu'à la gateway.
 */
function fetchAsProfile(profile: string): typeof fetch {
  return (input, init) =>
    fetch(input, {
      ...init,
      headers: {
        ...Object.fromEntries(new Headers(init?.headers).entries()),
        [PROFILE_HEADER]: profile,
        ...(process.env.SORABEL_KEY ? { "x-sorabel-key": process.env.SORABEL_KEY } : {}),
      },
    });
}

const runtime = new CopilotRuntime({
  // Fabrique par requête : un agent par profil, la connexion MCP en hérite.
  agents: ({ request }) => {
    const profile = resolveProfile(request);
    return {
      default: new BuiltInAgent({
        model: MODEL,
        apiKey: process.env.GOOGLE_API_KEY || undefined,
        maxSteps: 8,
        prompt:
          "Tu es l'assistant interne Sorabel. Tu réponds en français, brièvement. " +
          "Tu ne réponds qu'à partir des tools de la gateway : n'invente jamais " +
          "une donnée produit, un stock ou un chiffre. Si un tool refuse, explique " +
          "le refus à l'utilisateur au lieu de contourner.",
        mcpServers: [
          { type: "http", url: MCP_URL, options: { fetch: fetchAsProfile(profile) } },
        ],
      }),
    };
  },
});

const app = createCopilotEndpoint({ runtime, basePath: "/api/copilotkit" });

const handler = (request: Request) => app.fetch(request);
export { handler as GET, handler as POST, handler as OPTIONS };
