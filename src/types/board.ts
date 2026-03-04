export type BoardStatus = 'waiting' | 'flashing' | 'done' | 'error';

export interface BoardModule {
  serial: string;
  progress: number;
  status: BoardStatus;
  currentStep: string | null;
  startTime: number | null; // Unix timestamp (seconds)
}

// Key = IP address
export type ModulesMap = Record<string, BoardModule>;
