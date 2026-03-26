export type BoardStatus = 'waiting' | 'flashing' | 'done' | 'error';

export interface BoardModule {
  serial: string;
  progress: number;
  status: BoardStatus;
  currentStep: string | null;
  startTime: number | null; // Unix timestamp (seconds)
  errorMessage: string | null; // Set when status === 'error'
}

// Key = IP address
export type ModulesMap = Record<string, BoardModule>;

// ── Position slot system (5 Mallow Carrier Boards) ──

export type SlotState =
  | 'empty'          // No scan, slot inactive
  | 'awaiting_card'  // Position scanned, waiting for card insertion + Enter
  | 'awaiting_boot'  // Card confirmed inserted, waiting for DHCP/TCP detection
  | 'flashing'       // Card detected, flashing in progress
  | 'done'           // Flash completed successfully
  | 'error';         // Flash failed

export interface PositionSlot {
  state: SlotState;
  boardIp: string | null;
  boardData: BoardModule | null;
  scannedAt: number | null;  // Unix timestamp ms
}

export const NUM_POSITIONS = 5;

export function createEmptySlot(): PositionSlot {
  return { state: 'empty', boardIp: null, boardData: null, scannedAt: null };
}
