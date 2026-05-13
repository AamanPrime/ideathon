export type CustomerHistoryItem = {
  id: string;
  at: string;
  title: string;
  detail: string;
};

const STORAGE_PREFIX = "ideathon_crm_demo_";

function keyFor(customerId: string): string {
  return `${STORAGE_PREFIX}${customerId.trim().toUpperCase()}`;
}

export function loadHistory(customerId: string): CustomerHistoryItem[] {
  if (!customerId.trim()) return [];
  try {
    const raw = localStorage.getItem(keyFor(customerId));
    if (!raw) return seedDemo(customerId);
    return JSON.parse(raw) as CustomerHistoryItem[];
  } catch {
    return seedDemo(customerId);
  }
}

function seedDemo(customerId: string): CustomerHistoryItem[] {
  const id = customerId.trim().toUpperCase();
  if (!id) return [];
  const demo: CustomerHistoryItem[] = [
    {
      id: crypto.randomUUID(),
      at: new Date(Date.now() - 86400000 * 5).toISOString(),
      title: "Cheque book request",
      detail: "Requested 25 leaves; dispatched to regd. address.",
    },
    {
      id: crypto.randomUUID(),
      at: new Date(Date.now() - 86400000 * 2).toISOString(),
      title: "UPI limit revision",
      detail: "Daily UPI limit raised per tier; OTP verified.",
    },
  ];
  saveHistory(id, demo);
  return demo;
}

export function saveHistory(customerId: string, items: CustomerHistoryItem[]): void {
  localStorage.setItem(keyFor(customerId), JSON.stringify(items.slice(0, 20)));
}

export function appendHistory(customerId: string, entry: Omit<CustomerHistoryItem, "id" | "at">): void {
  const id = customerId.trim().toUpperCase();
  if (!id) return;
  const list = loadHistory(id);
  const row: CustomerHistoryItem = {
    id: crypto.randomUUID(),
    at: new Date().toISOString(),
    title: entry.title,
    detail: entry.detail,
  };
  saveHistory(id, [row, ...list]);
}
