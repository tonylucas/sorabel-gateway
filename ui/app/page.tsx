"use client";

import { useState } from "react";
import { CopilotKit } from "@copilotkit/react-core";
import { CopilotChat } from "@copilotkit/react-ui";
import "@copilotkit/react-ui/styles.css";

const PROFILES = ["support", "commercial", "dev"] as const;

export default function Page() {
  const [profile, setProfile] = useState<(typeof PROFILES)[number]>("support");

  return (
    <main className="flex h-screen flex-col">
      <header className="flex items-center gap-3 border-b px-4 py-3">
        <span className="font-semibold">Sorabel — assistant interne</span>
        <select
          className="ml-auto rounded border px-2 py-1 text-sm"
          value={profile}
          onChange={(e) => setProfile(e.target.value as (typeof PROFILES)[number])}
        >
          {PROFILES.map((p) => (
            <option key={p} value={p}>
              profil : {p}
            </option>
          ))}
        </select>
      </header>

      {/* La clé force le remontage à chaque changement de profil : la session MCP
          est renégociée, et l'historique d'un autre profil ne fuit pas. */}
      <CopilotKit
        key={profile}
        runtimeUrl="/api/copilotkit"
        headers={{ "X-Sorabel-Profile": profile }}
      >
        <CopilotChat
          className="flex-1 overflow-hidden"
          labels={{
            initial:
              "Bonjour. Posez une question, ou tapez « appelle ping » pour vérifier la gateway.",
          }}
        />
      </CopilotKit>
    </main>
  );
}
