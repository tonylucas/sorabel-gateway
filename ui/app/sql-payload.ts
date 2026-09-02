/**
 * Lecture du résultat de `ask_database`, hors de tout JSX pour rester testable.
 *
 * Le résultat traverse deux enveloppes avant d'arriver ici : celle de MCP
 * (`content[].text`), puis celle de la gateway (`{status, payload, message}`).
 * La seconde est du JSON dans une chaîne — d'où le double `JSON.parse`.
 */

export type Vue =
  | { type: "illisible" }
  | { type: "refus"; message: string }
  | { type: "scalaire"; sql?: string }
  | { type: "vide"; sql?: string }
  | { type: "tableau"; sql?: string; rows: unknown[][]; columns: string[] };

type Enveloppe = {
  status?: string;
  message?: string;
  payload?: { sql?: string; rows?: unknown[][]; columns?: string[] };
};

function deballe(result: string): Enveloppe | null {
  try {
    const mcp = JSON.parse(result);
    const bloc = mcp?.content?.find((part: { type?: string }) => part?.type === "text");
    return typeof bloc?.text === "string" ? JSON.parse(bloc.text) : mcp;
  } catch {
    return null;
  }
}

export function vue(result: string): Vue {
  const enveloppe = deballe(result);
  if (!enveloppe) return { type: "illisible" };

  const { sql, rows = [], columns = [] } = enveloppe.payload ?? {};

  // Refus et demandes de clarification : la gateway ne renvoie volontairement
  // pas le SQL dans ce cas, le nom d'une colonne protégée n'a pas à redescendre
  // jusqu'au client. Il n'y a donc rien à replier.
  if (enveloppe.status !== "ok") {
    return { type: "refus", message: enveloppe.message || "La base a refusé la question." };
  }

  // Un COUNT ne se met pas en tableau : la phrase de l'agent porte déjà le
  // chiffre, le composant n'ajoute que la requête.
  if (rows.length === 1 && columns.length === 1) return { type: "scalaire", sql };

  // Zéro ligne est justement le cas où l'on veut voir la requête, pour
  // comprendre pourquoi c'est vide.
  if (rows.length === 0) return { type: "vide", sql };

  return { type: "tableau", sql, rows, columns };
}

type MessageLike = {
  role?: string;
  toolCalls?: { function?: { name?: string } }[];
};

/**
 * Retire la synthèse que l'agent rédige après `ask_database` : le tableau
 * affiche déjà les lignes, et rien ne permet d'empêcher ce message à la source.
 * Il vient de la boucle multi-étapes du `BuiltInAgent`, côté serveur ;
 * `followUp: false` ne gouverne que les tools frontend.
 *
 * Un seul message est masqué par interrogation : ce qui suit un autre tool, ou
 * une nouvelle question, reste visible.
 */
export function sansSyntheseSql<T extends MessageLike>(messages: T[]): T[] {
  let aInterroge = false;
  return messages.filter((message) => {
    if (message.role === "user") {
      aInterroge = false;
      return true;
    }
    if (message.role !== "assistant") return true;

    const appels = message.toolCalls ?? [];
    if (appels.length > 0) {
      aInterroge = appels.some((appel) => appel.function?.name === "ask_database");
      return true;
    }
    if (aInterroge) {
      aInterroge = false;
      return false;
    }
    return true;
  });
}
