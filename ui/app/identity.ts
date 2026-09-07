/**
 * Le jeton d'identité qui ouvre la gateway.
 *
 * `sorabel-mcp` est déployé en authentification requise : Cloud Run refuse la
 * requête à son frontend, avant même d'atteindre le conteneur, si elle n'est pas
 * signée. C'est l'app bot qui la signe, avec le jeton que le serveur de
 * métadonnées de l'instance émet pour son compte de service.
 *
 * L'audience est l'URL du service appelé, **chemin exclu** : c'est elle que
 * Cloud Run compare, et un jeton émis pour une autre audience est rejeté comme
 * s'il n'y en avait pas.
 */

const METADATA =
  "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity";

/** Le jeton vaut une heure ; reprise un peu avant, pour ne pas jouer avec l'horloge. */
const DUREE_MS = 55 * 60_000;

/** Un jeton par audience : il la porte, il n'est pas interchangeable. */
const cache = new Map<string, { jeton: string; expire: number }>();

export async function identityToken(audience: string): Promise<string | null> {
  // `K_SERVICE` n'est posée que par Cloud Run. Hors de là il n'y a pas de
  // serveur de métadonnées à interroger, et la gateway locale n'exige rien :
  // mieux vaut ce test qu'un échec DNS à chaque appel.
  if (!process.env.K_SERVICE) return null;

  const connu = cache.get(audience);
  if (connu && Date.now() < connu.expire) return connu.jeton;

  const reponse = await fetch(`${METADATA}?audience=${encodeURIComponent(audience)}`, {
    headers: { "Metadata-Flavor": "Google" },
  });
  if (!reponse.ok) {
    throw new Error(
      `jeton d'identité refusé par le serveur de métadonnées (${reponse.status}) — ` +
        `audience ${audience} ; vérifier que le service tourne sous un compte de service`,
    );
  }

  const jeton = (await reponse.text()).trim();
  cache.set(audience, { jeton, expire: Date.now() + DUREE_MS });
  return jeton;
}
