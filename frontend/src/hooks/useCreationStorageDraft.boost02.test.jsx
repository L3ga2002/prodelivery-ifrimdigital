import { act, StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import axios from 'axios';
import { createOrderRecovery } from '../lib/orderCreationRecovery';
import { useOrderCreationRecovery } from './useOrderCreationRecovery';
jest.mock('axios', () => ({ create: jest.fn() }));
const ID = '123e4567-e89b-42d3-a456-426614174000', KEY = 'prodelivery:order-create:v1:actor', DRAFT = `${KEY}:draft:${ID}`;
const record = { version: 1, actor_id: 'actor', client_operation_id: ID, created_at: 1, receipt: null };
const draft = { actor_id: 'actor', client_operation_id: ID, order: { restaurant_id: 'r', customer_name: 'Private clone', customer_phone: '0700000000', customer_address: 'Private inherited address', items: [], total_amount: 26, payment_type: 'CASH', source: 'S' } };
const applied = { ...record, receipt: { client_operation_id: ID, state: 'applied', order_id: 'order', order_version: 0 } };
let root, node, recovery;
function Harness() { recovery = useOrderCreationRecovery('actor', 'https://qa.invalid', false); return null; }
const event = (oldValue, newValue) => act(async () => window.dispatchEvent(new StorageEvent('storage', { key: KEY, oldValue, newValue })));
beforeEach(() => {
 globalThis.IS_REACT_ACT_ENVIRONMENT = true; localStorage.clear(); sessionStorage.clear();
 Object.defineProperty(navigator, 'locks', { configurable: true, value: { request: async (_k, _o, cb) => cb({}) } });
 axios.create.mockReturnValue({ get: jest.fn(), post: jest.fn() }); node = document.createElement('div'); document.body.append(node); root = createRoot(node);
 localStorage.setItem(KEY, JSON.stringify(record)); sessionStorage.setItem(DRAFT, JSON.stringify(draft));
});
afterEach(async () => { await act(async () => root.unmount()); node.remove(); });
test('inherited child-tab payload clears on terminal storage receipt, while identity remains', async () => {
 await act(async () => root.render(<StrictMode><Harness /></StrictMode>)); expect(sessionStorage.getItem(DRAFT)).not.toBeNull();
 localStorage.setItem(KEY, JSON.stringify(applied)); await event(JSON.stringify(record), JSON.stringify(applied));
 expect(recovery.record.receipt.state).toBe('applied'); expect(sessionStorage.getItem(DRAFT)).toBeNull(); expect(localStorage.getItem(KEY)).toBe(JSON.stringify(applied));
});
test('queued ACK removal still cleans inherited exact draft using validated old receipt', async () => {
 await act(async () => root.render(<StrictMode><Harness /></StrictMode>)); localStorage.removeItem(KEY);
 await event(JSON.stringify(applied), null); expect(recovery.record).toBeNull(); expect(sessionStorage.getItem(DRAFT)).toBeNull();
 expect(axios.create.mock.results[0].value.post).not.toHaveBeenCalled();
});


test.each([JSON.stringify({ ...applied, actor_id: 'foreign' }), '{bad', JSON.stringify(record)])('foreign/invalid/nonterminal storage event does not discard own draft %s', async (raw) => {
 await act(async () => root.render(<StrictMode><Harness /></StrictMode>)); const exact = sessionStorage.getItem(DRAFT);
 await event(raw, null); expect(sessionStorage.getItem(DRAFT)).toBe(exact); expect(recovery.record.client_operation_id).toBe(ID);
});
test('terminal receipt already present on mount clears clone without ACKing durable identity', async () => {
 localStorage.setItem(KEY, JSON.stringify(applied)); await act(async () => root.render(<StrictMode><Harness /></StrictMode>));
 expect(sessionStorage.getItem(DRAFT)).toBeNull(); expect(localStorage.getItem(KEY)).toBe(JSON.stringify(applied));
});

// Direct-controller probes: fake API/locks; these do not claim real BFCache.
function direct(owner = () => true, api = { get: jest.fn(), post: jest.fn() }) {
 return createOrderRecovery({ actorId: 'actor', api, durableStorage: localStorage,
 draftStorage: sessionStorage, locks: { request: async (_k, _o, cb) => cb({}) },
 crypto: { randomUUID: () => ID }, isOwnerActive: owner });
}
test('suspended direct snapshot preserves exact payload despite peer terminal receipt', () => {
 const c = direct(); const exact = sessionStorage.getItem(DRAFT); c.snapshot(); c.deactivate({ preserveDraft: true });
 localStorage.setItem(KEY, JSON.stringify(applied)); expect(c.snapshot().receipt.state).toBe('applied');
 expect(sessionStorage.getItem(DRAFT)).toBe(exact);
});
test('inactive owner direct snapshot preserves exact payload despite peer terminal receipt', () => {
 let owner = true; const c = direct(() => owner); const exact = sessionStorage.getItem(DRAFT); c.snapshot(); owner = false;
 localStorage.setItem(KEY, JSON.stringify(applied)); expect(c.snapshot().receipt.state).toBe('applied');
 expect(sessionStorage.getItem(DRAFT)).toBe(exact);
});
test('old pending POST caller cannot clear peer receipt payload after a new lifecycle activates', async () => {
 let arm = false, tripped = false, c, exact;
 localStorage.removeItem(KEY); sessionStorage.removeItem(DRAFT);
 const api = { get: jest.fn(), post: jest.fn(async () => { exact = sessionStorage.getItem(DRAFT); arm = true; return { status: 202,
 data: { client_operation_id: ID, state: 'pending', retry_after_seconds: 1 } }; }) };
 c = direct(() => { if (arm && !tripped) { tripped = true; queueMicrotask(() => {
 c.deactivate({ preserveDraft: true }); c.activate(); localStorage.setItem(KEY, JSON.stringify(applied)); }); } return true; }, api);
 await expect(c.submit(draft.order)).rejects.toMatchObject({ code: 'SESSION_CHANGED' });
 expect(tripped).toBe(true); expect(api.post).toHaveBeenCalledTimes(1); expect(sessionStorage.getItem(DRAFT)).toBe(exact);
});
test('matching verified restore allows subsequent terminal snapshot cleanup without ACK', async () => {
 const api = { get: jest.fn(async () => ({ status: 200, data: { id: 'actor', role: 'admin' } })), post: jest.fn() };
 const c = direct(() => true, api); c.snapshot(); c.deactivate({ preserveDraft: true }); localStorage.setItem(KEY, JSON.stringify(applied));
 await c.restoreSession(); expect(c.snapshot().receipt.state).toBe('applied'); expect(sessionStorage.getItem(DRAFT)).toBeNull();
 expect(localStorage.getItem(KEY)).toBe(JSON.stringify(applied)); expect(api.post).not.toHaveBeenCalled();
});
test('explicit default logout still clears tracked payload after metadata removal', () => {
 const c = direct(); c.snapshot(); localStorage.removeItem(KEY); c.deactivate(); expect(sessionStorage.getItem(DRAFT)).toBeNull();
});
