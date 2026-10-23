import { api, type ModelCatalog, type ProviderRecord } from "./api";

let providers: ProviderRecord[] | null = null;
let providerRequest: Promise<ProviderRecord[]> | null = null;
const providerListeners = new Set<(value: ProviderRecord[]) => void>();
const catalogs = new Map<string, ModelCatalog>();
const catalogRequests = new Map<string, Promise<ModelCatalog>>();
const catalogListeners = new Map<string, Set<(value: ModelCatalog | null) => void>>();

function publishProviders(value: ProviderRecord[]): void {
  providerListeners.forEach((listener) => listener(value));
}

function publishCatalog(provider: string, value: ModelCatalog | null): void {
  catalogListeners.get(provider)?.forEach((listener) => listener(value));
}

export function subscribeProviders(listener: (value: ProviderRecord[]) => void): () => void {
  providerListeners.add(listener);
  return () => { providerListeners.delete(listener); };
}

export function subscribeModelCatalog(
  provider: string,
  listener: (value: ModelCatalog | null) => void,
): () => void {
  const listeners = catalogListeners.get(provider) || new Set();
  listeners.add(listener);
  catalogListeners.set(provider, listeners);
  return () => {
    listeners.delete(listener);
    if (!listeners.size) catalogListeners.delete(provider);
  };
}

export function cachedProviders(): ProviderRecord[] | null {
  return providers;
}

export function loadProviders(force = false): Promise<ProviderRecord[]> {
  if (providerRequest) return providerRequest;
  if (!force && providers) return Promise.resolve(providers);
  providerRequest = api.providers().then((result) => {
    providers = result;
    publishProviders(result);
    return result;
  }).finally(() => { providerRequest = null; });
  return providerRequest;
}

export function invalidateProviders(): void {
  providers = null;
}

export function cachedModelCatalog(provider: string): ModelCatalog | null {
  return catalogs.get(provider) || null;
}

export function loadModelCatalog(provider: string, force = false): Promise<ModelCatalog> {
  if (!provider) return Promise.resolve({ profile: "", protocol: "", models: [], fetched: false, error: "" });
  if (catalogRequests.has(provider)) return catalogRequests.get(provider)!;
  if (!force && catalogs.has(provider)) return Promise.resolve(catalogs.get(provider)!);
  const request = (force ? api.refreshModels(provider) : api.models(provider)).then((result) => {
    catalogs.set(provider, result);
    publishCatalog(provider, result);
    return result;
  }).finally(() => { catalogRequests.delete(provider); });
  catalogRequests.set(provider, request);
  return request;
}

export function invalidateModelCatalog(provider?: string): void {
  if (provider) {
    catalogs.delete(provider);
    publishCatalog(provider, null);
  } else {
    const keys = [...catalogs.keys()];
    catalogs.clear();
    keys.forEach((key) => publishCatalog(key, null));
  }
}

export async function rememberModel(provider: string, model: string): Promise<void> {
  const modelId = model.trim();
  if (!provider || !modelId) return;
  const current = catalogs.get(provider);
  if (current && !current.models.includes(modelId)) {
    const updated = {
      ...current,
      models: [...current.models, modelId].sort((left, right) => left.localeCompare(right)),
    };
    catalogs.set(provider, updated);
    publishCatalog(provider, updated);
  }
  await api.addModel(provider, modelId);
}
