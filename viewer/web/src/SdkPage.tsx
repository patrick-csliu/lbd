import { useEffect, useState } from "react";
import { api, SdkInfo, SdkLanguage } from "./api";
import { useToast } from "./toast";
import { HelpLink } from "./help";

export default function SdkPage() {
  const toast = useToast();
  const [info, setInfo] = useState<SdkInfo | null>(null);
  const [langId, setLangId] = useState<string | null>(null);

  useEffect(() => {
    api.sdk().then(setInfo).catch((e) => toast(e.message, "error"));
  }, [toast]);

  if (!info) return <div className="pad muted">Loading…</div>;
  if (info.languages.length === 0) {
    return (
      <div className="sdk-page">
        <h1>Language modules</h1>
        <p className="error-box">No language modules were found next to this viewer.</p>
      </div>
    );
  }
  // Languages come from the language.toml manifests; the first one is shown by default.
  const l = info.languages.find((x) => x.id === langId) ?? info.languages[0];
  const names = info.languages.map((x) => x.name);
  const nameList = names.length > 1 ? `${names.slice(0, -1).join(", ")} or ${names[names.length - 1]}` : names[0];

  return (
    <div className="sdk-page">
      <h1>
        Language modules <HelpLink page="getting-started/install.html" anchor="language-modules" topic="installing language modules" />
      </h1>
      <p>
        To write and read <code>.lbd</code> files from your own programs, install the module for each language you use.
        Installing the viewer does not change your {nameList}. You choose where each module goes.
      </p>
      <p className="note">
        This viewer is version <strong>{info.version}</strong> and uses LBD format <strong>{info.lbd_version}</strong>. Install
        the modules from this version so everything matches. Files written by a newer module version may need a newer viewer.
      </p>
      {!info.bundled && (
        <p className="note warn">
          Running from the source folder: the commands below point at the source code instead of packaged files.
        </p>
      )}

      <div className="lang-tabs" role="tablist">
        {info.languages.map((x) => (
          <button key={x.id} role="tab" aria-selected={x.id === l.id} className={x.id === l.id ? "active" : ""} onClick={() => setLangId(x.id)}>
            {x.name}
          </button>
        ))}
      </div>

      <LanguageSection l={l} onReveal={() => api.revealSdk(l.id).catch((e) => toast(e.message, "error"))} />
    </div>
  );
}

function LanguageSection({ l, onReveal }: { l: SdkLanguage; onReveal: () => void }) {
  return (
    <div className="lang-body" role="tabpanel">
      {l.error && <p className="note warn sdk-error">This module can't be set up from here: {l.error}</p>}
      {l.requirements && (
        <p>
          <strong>Requirements:</strong> {l.requirements}
        </p>
      )}
      <div className="row">
        <span className="muted small path">{l.folder}</span>
        <button onClick={onReveal} disabled={!l.available}>
          Open folder
        </button>
        {!l.available && <span className="error-text small">Module files not found</span>}
      </div>

      <h2>1. Install</h2>
      {l.install.map((c, i) => (
        <div key={i}>
          <p>{c.label}</p>
          <Code text={c.code} />
        </div>
      ))}

      {l.check && (
        <>
          <h2>2. Check that it works</h2>
          <Code text={l.check} />
        </>
      )}

      {l.example && (
        <>
          <h2>3. Try it</h2>
          <p>
            Writes <code>example.lbd</code> in the current folder and reads it back. Open the file here to see it plotted.
            {l.example_file && (
              <>
                {" "}
                The same code is in <code>{l.example_file}</code> in the folder above.
              </>
            )}
          </p>
          <Code text={l.example} />
        </>
      )}

      {l.upgrade && (
        <>
          <h2>Upgrade</h2>
          <Code text={l.upgrade} />
        </>
      )}

      {l.uninstall && (
        <>
          <h2>Uninstall</h2>
          <Code text={l.uninstall} />
        </>
      )}

      {l.notes.length > 0 && (
        <>
          <h2>Notes</h2>
          <ul>
            {l.notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function Code({ text }: { text: string }) {
  const toast = useToast();
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      toast("Copied");
    } catch {
      toast("Couldn't copy; select the text and copy it manually", "error");
    }
  };
  return (
    <div className="code">
      <pre>{text}</pre>
      <button className="copy" onClick={copy}>
        Copy
      </button>
    </div>
  );
}
