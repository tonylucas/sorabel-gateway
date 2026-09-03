import assert from "node:assert/strict";
import { test } from "node:test";
import { vue } from "./sql-payload.ts";

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

test("un résultat illisible ne fait pas tomber le rendu", () => {
  assert.deepEqual(vue("pas du json"), { type: "illisible" });
});
