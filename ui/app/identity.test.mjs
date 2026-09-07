import assert from "node:assert/strict";
import { test } from "node:test";
import { identityToken } from "./identity.ts";

/** Le cache est indexé par audience : une par test suffit à l'isoler. */
let appels = [];

function stubMetadata(reponse) {
  appels = [];
  globalThis.fetch = async (url, init) => {
    appels.push({ url: String(url), init });
    return reponse;
  };
}

const ok = (texte) => ({ ok: true, status: 200, text: async () => texte });

test("hors Cloud Run, pas de jeton et pas d'appel au serveur de métadonnées", async () => {
  delete process.env.K_SERVICE;
  stubMetadata(ok("jamais"));
  assert.equal(await identityToken("https://hors-ligne.run.app"), null);
  assert.equal(appels.length, 0);
});

test("sur Cloud Run, le jeton est demandé pour l'audience et mis en cache", async () => {
  process.env.K_SERVICE = "sorabel-ui";
  stubMetadata(ok("  jeton-abc\n"));

  const audience = "https://sorabel-mcp.run.app";
  assert.equal(await identityToken(audience), "jeton-abc");
  assert.equal(await identityToken(audience), "jeton-abc");

  assert.equal(appels.length, 1, "le second appel doit venir du cache");
  assert.ok(appels[0].url.endsWith(`?audience=${encodeURIComponent(audience)}`));
  assert.equal(appels[0].init.headers["Metadata-Flavor"], "Google");
});

test("un refus du serveur de métadonnées ne passe pas pour une absence de jeton", async () => {
  process.env.K_SERVICE = "sorabel-ui";
  stubMetadata({ ok: false, status: 403, text: async () => "" });
  await assert.rejects(() => identityToken("https://refuse.run.app"), /403/);
});
