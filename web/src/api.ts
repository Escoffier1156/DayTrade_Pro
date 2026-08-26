import type { TargetsResponse, TradeLog } from './types';

const token = new URLSearchParams(location.search).get('k') ?? '';

function withToken(path: string): string {
  if (!token) return path;
  return `${path}?k=${token}`;
}

export const api = {
  getTargets: async (): Promise<TargetsResponse> => {
    const res = await fetch(withToken('/api/targets'), { cache: 'no-store' });
    if (!res.ok) throw new Error(`/api/targets returned ${res.status}`);
    return (await res.json()) as TargetsResponse;
  },
  getHistory: async (): Promise<TradeLog[]> => {
    const res = await fetch(withToken('/api/history'), { cache: 'no-store' });
    if (!res.ok) throw new Error(`/api/history returned ${res.status}`);
    return (await res.json()) as TradeLog[];
  }
};
