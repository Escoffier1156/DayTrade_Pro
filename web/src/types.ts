export interface Target {
  code: string;
  name: string;
  sector: string;
  entry_price: number;
  shares: number;
  stop: number;
  target: number;
  status: "OPEN" | "HIT_TP" | "HIT_SL";
  latest_price: number;
  volume?: number;
  turnover?: number;
  vwap?: number;
  trades?: number;
  history?: { time: number; value: number }[];
}

export interface TargetsResponse {
  date: string;
  targets: Target[];
}

export interface TradeLog {
  time: string;
  ticker: string;
  name: string;
  side: string;
  qty: number;
  price: number;
  pnl: number;
}

