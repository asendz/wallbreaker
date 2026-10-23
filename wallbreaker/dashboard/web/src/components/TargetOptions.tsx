import { useEffect, useState } from "react";
import { api, type TargetOptions as TargetOptionsT } from "../api";

const DEFAULTS: TargetOptionsT = { modality: "auto", system_mode: "default", provider: "", judge_enabled: true };

export function TargetOptions() {
  const [value, setValue] = useState<TargetOptionsT>(DEFAULTS);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");

  useEffect(() => {
    api.settings().then((settings) => setValue(settings.target_options || DEFAULTS)).catch((error) => setStatus((error as Error).message));
  }, []);

  const save = async () => {
    setBusy(true); setStatus("");
    try {
      const settings = await api.saveSettings({ target_options: value });
      setValue(settings.target_options || DEFAULTS);
      setStatus("saved");
    } catch (error) {
      setStatus((error as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return <details className="settings-drawer" open>
    <summary><span><b>Target delivery</b><small>Configure how every console and agent run reaches the selected target</small></span></summary>
    <div className="drawer-body">
      <div className="form-grid">
        <label>Modality<select value={value.modality} onChange={(event) => setValue({ ...value, modality: event.target.value as TargetOptionsT["modality"] })}>
          <option value="auto">Auto-detect from model</option><option value="text">Text</option><option value="image">Image generation</option>
        </select></label>
        <label>System prompt delivery<select value={value.system_mode} onChange={(event) => setValue({ ...value, system_mode: event.target.value as TargetOptionsT["system_mode"] })}>
          <option value="default">Native system message</option><option value="merge">Merge into first user message</option><option value="drop">Discard system prompt</option>
        </select></label>
        <label className="wide">OpenRouter backend pin<input value={value.provider} placeholder="None, or WandB, Alibaba" onChange={(event) => setValue({ ...value, provider: event.target.value })} /></label>
        <label className="toggle-field"><input type="checkbox" checked={value.judge_enabled} onChange={(event) => setValue({ ...value, judge_enabled: event.target.checked })} /><span>Use the configured LLM judge</span></label>
      </div>
      <div className="mono muted">Comma-separate fallback backends. With the LLM judge off, text runs use the local heuristic and image runs are recorded as ungraded.</div>
      <div className="editor-actions"><button type="button" className="primary-command" disabled={busy} onClick={() => void save()}>{busy ? "Saving..." : "Save target delivery"}</button>{status && <span className="mono muted">{status}</span>}</div>
    </div>
  </details>;
}
