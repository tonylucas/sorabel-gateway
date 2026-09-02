"use client";

import { useComponent } from "@copilotkit/react-core/v2";
import { z } from "zod";

/**
 * Les champs d'une fiche technique, tels qu'ils sortent de `get_document`.
 * Tout est optionnel sauf la référence et le titre : l'agent remplit ce que la
 * fiche contient, et les props arrivent partielles pendant le streaming.
 */
const FICHE = z.object({
  reference: z
    .string()
    .describe("Référence produit, telle qu'écrite dans la fiche, ex. « REF-1459 »"),
  titre: z.string().describe("Libellé du produit"),
  fabricant: z.string().optional(),
  categorie: z.string().optional(),
  version: z.string().optional(),
  date: z.string().optional().describe("Date du document, format AAAA-MM-JJ"),
  prix_ht: z
    .string()
    .optional()
    .describe("Prix public HT, unité comprise, ex. « 420.27 EUR / pièce »"),
  caracteristiques: z
    .array(z.string())
    .optional()
    .describe("Une entrée par ligne de la rubrique « Caractéristiques »"),
  accessoires: z.array(z.string()).optional().describe("Références des produits associés"),
  fichier: z
    .string()
    .optional()
    .describe("Nom de fichier exact du document, ex. « REF-1459-v1.0.pdf »"),
});

function FicheCard({
  reference,
  titre,
  fabricant,
  categorie,
  version,
  date,
  prix_ht,
  caracteristiques,
  accessoires,
  fichier,
}: z.infer<typeof FICHE>) {
  const infos: [string, string | undefined][] = [
    ["Fabricant", fabricant],
    ["Catégorie", categorie],
    ["Prix public HT", prix_ht],
  ];

  return (
    <article className="my-2 max-w-md rounded-lg border p-4 text-sm">
      <div className="flex items-baseline gap-2">
        <span className="rounded border px-1.5 py-0.5 font-mono text-xs">{reference || "…"}</span>
        {version && <span className="text-xs opacity-60">version {version}</span>}
      </div>
      <h3 className="mt-1 font-semibold">{titre || "…"}</h3>

      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        {infos
          .filter(([, valeur]) => valeur)
          .map(([libelle, valeur]) => (
            <div key={libelle} className="contents">
              <dt className="opacity-60">{libelle}</dt>
              <dd>{valeur}</dd>
            </div>
          ))}
      </dl>

      {caracteristiques && caracteristiques.length > 0 && (
        <ul className="mt-3 list-disc pl-4 opacity-80">
          {caracteristiques.map((ligne) => (
            <li key={ligne}>{ligne}</li>
          ))}
        </ul>
      )}

      {accessoires && accessoires.length > 0 && (
        <p className="mt-3 opacity-60">Produits associés : {accessoires.join(", ")}</p>
      )}

      {(fichier || date) && (
        <footer className="mt-3 border-t pt-2 font-mono text-xs opacity-60">
          {[fichier, date].filter(Boolean).join(" · ")}
        </footer>
      )}
    </article>
  );
}

/**
 * Enregistre `afficher_fiche` auprès du runtime. Le composant ne rend rien
 * lui-même : c'est l'agent qui décide d'appeler le tool, et CopilotKit qui
 * insère la carte dans le fil de conversation.
 */
export function FicheTool() {
  useComponent({
    name: "afficher_fiche",
    description:
      "Affiche la fiche technique d'un produit sous forme de carte. À utiliser " +
      "après `get_document` ou `search_docs`, quand la réponse porte sur une " +
      "fiche technique précise. Ne recopier que des valeurs présentes dans le " +
      "document renvoyé par le tool : ne jamais compléter de mémoire, laisser " +
      "vide un champ absent. Accompagner la carte d'une phrase, pas d'une " +
      "redite de son contenu.",
    parameters: FICHE,
    render: FicheCard,
  });
  return null;
}
