import assert from "node:assert/strict";
import { test } from "node:test";
import { sansSyntheseSql, vue } from "./sql-payload.ts";

/** Ce que le runtime sérialise : enveloppe MCP contenant l'enveloppe gateway. */
const resultat = (enveloppe) =>
  JSON.stringify({
    content: [{ type: "text", text: JSON.stringify(enveloppe) }],
    isError: false,
  });

const gateway = (payload, status = "ok", message = "") => ({ status, payload, message });

test("un COUNT ne fait pas un tableau", () => {
  const sql = "SELECT COUNT(*) AS _col_0 FROM clients AS clients WHERE clients.ville = 'Lille'";
  assert.deepEqual(vue(resultat(gateway({ sql, rows: [[2]], columns: ["_col_0"] }))), {
    type: "scalaire",
    sql,
  });
});

test("zéro ligne garde la requête, c'est elle qui explique le vide", () => {
  const v = vue(resultat(gateway({ sql: "SELECT 1", rows: [], columns: ["a"] })));
  assert.equal(v.type, "vide");
  assert.equal(v.sql, "SELECT 1");
});

test("plusieurs lignes font un tableau", () => {
  const payload = {
    sql: "SELECT 1",
    rows: [
      [1, "Lille"],
      [2, "Lyon"],
    ],
    columns: ["id", "ville"],
  };
  const v = vue(resultat(gateway(payload)));
  assert.equal(v.type, "tableau");
  assert.deepEqual(v.columns, ["id", "ville"]);
  assert.equal(v.rows.length, 2);
});

test("une seule ligne mais plusieurs colonnes reste un tableau", () => {
  const payload = { sql: "SELECT 1", rows: [[1, "Lille"]], columns: ["id", "ville"] };
  assert.equal(vue(resultat(gateway(payload))).type, "tableau");
});

test("un refus n'expose pas de requête", () => {
  const v = vue(resultat(gateway({ code: "hors_schema" }, "refused", "Colonne inconnue.")));
  assert.deepEqual(v, { type: "refus", message: "Colonne inconnue." });
});

test("une demande de clarification passe par la même branche", () => {
  const v = vue(resultat(gateway({ code: "ambigu" }, "clarification", "Quelle période ?")));
  assert.deepEqual(v, { type: "refus", message: "Quelle période ?" });
});

/** La séquence réelle : appel, résultat, puis la synthèse dans un message à part. */
const interrogation = (synthese) => [
  { role: "user", content: "quels clients à lille ?" },
  { role: "assistant", toolCalls: [{ function: { name: "ask_database" } }] },
  { role: "tool", content: "{…}" },
  { role: "assistant", content: synthese },
];

const roles = (messages) => messages.map((m) => m.role + (m.toolCalls ? "+tool" : ""));

test("la synthèse qui suit ask_database est masquée", () => {
  const gardes = sansSyntheseSql(interrogation("Il y a deux clients à Lille."));
  assert.deepEqual(roles(gardes), ["user", "assistant+tool", "tool"]);
});

test("la synthèse d'un autre tool reste visible", () => {
  const messages = [
    { role: "user", content: "la garantie du REF-1459 ?" },
    { role: "assistant", toolCalls: [{ function: { name: "answer_question" } }] },
    { role: "tool", content: "{…}" },
    { role: "assistant", content: "Deux ans." },
  ];
  assert.equal(sansSyntheseSql(messages).length, 4);
});

test("la question suivante garde sa réponse", () => {
  const messages = [
    ...interrogation("Il y a deux clients à Lille."),
    { role: "user", content: "et à Lyon ?" },
    { role: "assistant", content: "Je ne sais pas sans interroger la base." },
  ];
  const gardes = sansSyntheseSql(messages);
  assert.equal(gardes.length, 5);
  assert.equal(gardes.at(-1).content, "Je ne sais pas sans interroger la base.");
});

test("deux interrogations de suite masquent deux synthèses", () => {
  const messages = [...interrogation("Deux à Lille."), ...interrogation("Trois à Lyon.")];
  assert.deepEqual(roles(sansSyntheseSql(messages)), [
    "user",
    "assistant+tool",
    "tool",
    "user",
    "assistant+tool",
    "tool",
  ]);
});

test("un résultat illisible ne fait pas tomber le rendu", () => {
  assert.deepEqual(vue("pas du json"), { type: "illisible" });
});
