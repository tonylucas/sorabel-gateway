"use client";

import {
  CopilotChatMessageView,
  type CopilotChatMessageViewProps,
  useRenderTool,
} from "@copilotkit/react-core/v2";
import { z } from "zod";
import { sansSyntheseSql, vue } from "./sql-payload";

/**
 * Vue de messages du chat, à passer en slot `messageView`. Elle n'existe que
 * pour retirer la synthèse rédigée après `ask_database` : le tableau est la
 * réponse, la répéter en prose en ferait deux.
 */
export const VueMessages = Object.assign(
  ({ messages, ...props }: CopilotChatMessageViewProps) => (
    <CopilotChatMessageView {...props} messages={sansSyntheseSql(messages ?? [])} />
  ),
  // Le slot est typé sur `CopilotChatMessageView`, statique `Cursor` compris.
  { Cursor: CopilotChatMessageView.Cursor },
);

function RequeteSQL({ sql }: { sql?: string }) {
  if (!sql) return null;
  return (
    <details className="mt-2">
      <summary className="cursor-pointer text-xs opacity-60">Requête SQL exécutée</summary>
      <pre className="mt-1 overflow-x-auto rounded border p-2 font-mono text-xs">{sql}</pre>
    </details>
  );
}

function cellule(valeur: unknown): string {
  return valeur === null || valeur === undefined ? "—" : String(valeur);
}

/**
 * Rend le résultat de `ask_database`. Contrairement à la carte fiche, rien
 * n'est recopié par le modèle : les lignes affichées sont celles que la gateway
 * a renvoyées. Le modèle décide d'interroger la base, pas de ce qui s'affiche.
 */
export function TableauSQL() {
  useRenderTool(
    {
      name: "ask_database",
      parameters: z.object({ question: z.string() }),
      render: (props) => {
        if (props.status !== "complete") {
          return <p className="my-2 text-sm opacity-60">Interrogation de la base…</p>;
        }

        const resultat = vue(props.result);

        if (resultat.type === "illisible") {
          return <p className="my-2 text-sm opacity-60">Résultat de la base illisible.</p>;
        }

        if (resultat.type === "refus") {
          return <p className="my-2 rounded border px-3 py-2 text-sm">{resultat.message}</p>;
        }

        if (resultat.type === "scalaire") {
          return (
            <div className="my-2 text-sm">
              <RequeteSQL sql={resultat.sql} />
            </div>
          );
        }

        if (resultat.type === "vide") {
          return (
            <div className="my-2 text-sm">
              <p className="opacity-60">Aucune ligne ne répond à cette question.</p>
              <RequeteSQL sql={resultat.sql} />
            </div>
          );
        }

        const { rows, columns, sql } = resultat;
        return (
          <div className="my-2 text-sm">
            <p className="mb-1 text-xs opacity-60">
              {rows.length} ligne{rows.length > 1 ? "s" : ""}
            </p>
            <div className="max-h-80 overflow-auto rounded border">
              <table className="w-full border-collapse text-left">
                <thead className="sticky top-0 bg-background">
                  <tr>
                    {columns.map((colonne) => (
                      <th key={colonne} className="border-b px-2 py-1 font-medium opacity-60">
                        {colonne}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((ligne, i) => (
                    // Les lignes ne sont ni réordonnées ni filtrées : l'index
                    // est une clé stable.
                    <tr key={i}>
                      {ligne.map((valeur, j) => (
                        <td key={j} className="border-b px-2 py-1">
                          {cellule(valeur)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <RequeteSQL sql={sql} />
          </div>
        );
      },
    },
    [],
  );
  return null;
}
