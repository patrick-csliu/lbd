// Settings → Library → Show dates in: this computer's time zone, another one, or as written in each
// file. Only how dates look: the file, the sort and the date tree stay as they are.

import { useEffect, useMemo, useState } from "react";
import { api, AppState } from "./api";
import { knownZone } from "./libraryColumns";
import { Setting } from "./settingsUi";
import { useToast } from "./toast";

const OTHER = "other";

/** The time zones this browser knows, by name. */
function zoneNames(): string[] {
  const here = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const all = (Intl as unknown as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf?.("timeZone") ?? [];
  return [...new Set([...all, here, "UTC"])].sort();
}

export function DateZoneSetting({ zone, onSettings }: { zone: string; onSettings: (s: AppState) => void }) {
  const toast = useToast();
  const names = useMemo(zoneNames, []);
  const here = Intl.DateTimeFormat().resolvedOptions().timeZone;
  // choosing "Another time zone" shows the list; the setting changes when a zone is picked
  const [other, setOther] = useState(zone !== "local" && zone !== "file");
  useEffect(() => setOther(zone !== "local" && zone !== "file"), [zone]);
  const save = async (date_zone: string) => {
    try {
      onSettings(await api.setLibrary({ date_zone }));
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  const kind = other ? OTHER : zone;
  const unknown = zone !== "local" && zone !== "file" && !knownZone(zone);
  return (
    <Setting
      id="library.date_zone"
      name="Show dates in"
      help="How the Date column, the pictures and the Files sidebar show dates. A date's tooltip gives the other form. A file's Created line, the date tree and the date filter stay as written in the file; sorting is by the real moment."
    >
      <select
        aria-label="Show dates in"
        value={kind}
        onChange={(e) => {
          const v = e.target.value;
          if (v === OTHER) {
            setOther(true);
          } else {
            setOther(false);
            save(v);
          }
        }}
      >
        <option value="local">This computer's time zone ({here})</option>
        <option value={OTHER}>Another time zone</option>
        <option value="file">As written in the file</option>
      </select>
      {other && (
        <select aria-label="Time zone" value={names.includes(zone) ? zone : ""} onChange={(e) => e.target.value && save(e.target.value)}>
          <option value="">Choose a time zone…</option>
          {names.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      )}
      {unknown && <p className="field-error">This browser doesn't know the time zone "{zone}": dates are in this computer's time zone. Choose another.</p>}
    </Setting>
  );
}
