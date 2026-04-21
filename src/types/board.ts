export type BoardStatus = 'waiting' | 'flashing' | 'done' | 'error';

export interface BoardModule {
  serial: string;
  status: BoardStatus;
  startTime: number | null; // Unix timestamp (seconds)
  errorMessage: string | null; // Set when status === 'error'
  registeredAt: number; // Unix timestamp (seconds) when the board was registered
}

// Key = IP address
export type ModulesMap = Record<string, BoardModule>;

// ── Position slot system (5 Mallow Carrier Boards) ──

export type SlotState =
  | 'empty'          // No scan, slot inactive
  | 'awaiting_card'  // Position scanned, waiting for card barcode scan
  | 'awaiting_boot'  // Card barcode scanned, waiting for DHCP/TCP detection
  | 'flashing'       // Card detected, flashing in progress
  | 'done'           // Flash completed successfully
  | 'error';         // Flash failed

export interface PositionSlot {
  state: SlotState;
  boardIp: string | null;
  boardData: BoardModule | null;
  scannedAt: number | null;  // Unix timestamp ms
  /** Expected serial number extracted from card barcode (last 8 digits) */
  expectedSerial: string | null;
  /** IPs previously cleared from this slot (prevents stale re-assignment) */
  clearedIps: Set<string>;
}

export const NUM_POSITIONS = 5;

export function createEmptySlot(): PositionSlot {
  return { state: 'empty', boardIp: null, boardData: null, scannedAt: null, expectedSerial: null, clearedIps: new Set() };
}
