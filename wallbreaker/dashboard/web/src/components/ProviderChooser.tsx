import { useEffect, useState } from "react";
import type { ProviderRecord } from "../api";
import { cachedProviders, loadProviders, subscribeProviders } from "../dataCache";

export function ProviderChooser({
  value, onChange, disabled = false, ariaLabel = "Provider",
}: {
  value: string;
  onChange: (value: string, provider?: ProviderRecord) => void;
  disabled?: boolean;
  ariaLabel?: string;
}) {
  const [providers, setProviders] = useState<ProviderRecord[]>(() => cachedProviders() || []);
  const [error, setError] = useState("");
  useEffect(() => {
    const unsubscribe = subscribeProviders(setProviders);
    void loadProviders().then(setProviders).catch((reason) => setError((reason as Error).message));
    return unsubscribe;
  }, []);
  return <>
    <select
      value={value}
      disabled={disabled}
      aria-label={ariaLabel}
      onChange={(event) => {
        const next = event.target.value;
        onChange(next, providers.find((provider) => provider.name === next));
      }}
    >
      {providers.filter((provider) => provider.enabled).map((provider) => (
        <option key={provider.name} value={provider.name}>{provider.name}</option>
      ))}
    </select>
    {error && <span className="err">{error}</span>}
  </>;
}
