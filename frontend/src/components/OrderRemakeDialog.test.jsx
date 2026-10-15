import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { OrderRemakeDialog, OrderRemakeRecoveryPanel } from './OrderRemakeDialog';
import { useOrderRemakeFinancePreview } from '../hooks/useOrderRemakeFinancePreview';
jest.mock('../hooks/useOrderRemakeFinancePreview', () => ({ useOrderRemakeFinancePreview: jest.fn() }));
jest.mock('./ui/dialog', () => { const Part = ({ children, ...p }) => <div data-testid={p['data-testid']}>{children}</div>; return { Dialog: ({ open, children }) => open ? <div>{children}</div> : null,
  DialogContent: Part, DialogHeader: Part, DialogTitle: Part, DialogDescription: Part, DialogFooter: Part }; });
let root, container, preview, recovery, props;
const node = (id) => container.querySelector(`[data-testid="${id}"]`);
const render = async (panel = false) => act(async () => root.render(panel ? <OrderRemakeRecoveryPanel recovery={recovery} isOnline={props.isOnline} /> : <OrderRemakeDialog {...props} recovery={recovery} />));
const change = async (id, value) => act(async () => { const el = node(id); const type = el.tagName === 'SELECT' ? HTMLSelectElement : el.tagName === 'TEXTAREA' ? HTMLTextAreaElement : HTMLInputElement;
  Object.getOwnPropertyDescriptor(type.prototype, 'value').set.call(el, value); el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); });
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true; localStorage.clear(); jest.clearAllMocks();
  preview = { context: null, tariffs: [{ version: 'v1', zone_ids: ['z1'] }], tariffVersion: '', quote: null, confirmed: false,
    readyToQuote: false, readyToSubmit: false, requestQuote: jest.fn(), refresh: jest.fn(), setTariffVersion: jest.fn(), confirm: jest.fn() };
  recovery = { available: true, blocked: false, busy: false, submit: jest.fn(async () => null), recover: jest.fn(), retrySubmission: jest.fn(), resume: jest.fn(), closeIntent: jest.fn(), acknowledge: jest.fn() };
  useOrderRemakeFinancePreview.mockImplementation(() => preview);
  props = { open: true, order: { id: 'parent', order_version: 4 }, actor: { id: 'owner', role: 'restaurant', restaurant_id: 'r1' },
    apiUrl: 'https://synthetic.invalid', token: 'token', isOnline: true, onClose: jest.fn(), originalFinancialRecovery: {} };
  container = document.createElement('div'); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });
test('money/payment/tariff start empty and quantities remain textual', async () => {
  await render(); expect(node('remake-price').value).toBe(''); expect(node('remake-payment').value).toBe(''); expect(node('remake-tariff').value).toBe('');
  await change('remake-price', '13,05'); await change('remake-quantity', '2');
  const options = useOrderRemakeFinancePreview.mock.calls.at(-1)[0]; expect(options.form.unit_price).toBe('13,05'); expect(options.form.quantity).toBe('2');
  expect(node('remake-submit').disabled).toBe(true);
});
test('quote is restaurant safe and explicit confirmation is separate', async () => {
  preview.quote = { products_bani: 1305, client_collection_bani: 1305, restaurant_transport_bani: 1600, advance_required_bani: 1305 };
  await render(); expect(node('remake-quote').textContent).toContain('13,05'); expect(container.textContent).not.toMatch(/Remunerație|courier/);
  await act(async () => node('remake-confirm-quote').click()); expect(preview.confirm).toHaveBeenCalledWith(true); expect(recovery.submit).not.toHaveBeenCalled();
});
test('double submit shares one in-flight call and hiding does not close intent', async () => {
  let resolve; recovery.submit.mockImplementation(() => new Promise((done) => { resolve = done; })); preview.readyToSubmit = true; preview.submission = { sentinel: 'confirmed' };
  await render(); await act(async () => { node('remake-submit').click(); node('remake-submit').click(); }); expect(recovery.submit).toHaveBeenCalledTimes(1);
  await act(async () => node('remake-hide').click()); expect(props.onClose).toHaveBeenCalledTimes(1); expect(recovery.closeIntent).not.toHaveBeenCalled();
  await act(async () => resolve(null));
});
test('original same-parent or malformed financial storage blocks even without an event', async () => {
  localStorage.setItem('prodelivery:order-financial-event:v1:owner:restaurant:r1', '{'); preview.readyToSubmit = true;
  await render(); expect(node('remake-submit').disabled).toBe(true); expect(container.querySelector('[role="alert"]')).not.toBeNull();
  expect(useOrderRemakeFinancePreview.mock.calls.at(-1)[0].enabled).toBe(false);
});
test.each(['pending', 'rejected', 'replayed'])('independent recovery panel exposes explicit actions for %s', async (state) => {
  recovery.record = { parent_id: 'parent', client_operation_id: 'operation_remake_0001', receipt: { state } }; await render(true);
  expect(node('remake-recovery-panel')).not.toBeNull(); expect(node('remake-acknowledge') !== null).toBe(state !== 'pending');
  expect(node('remake-resume') !== null).toBe(state === 'pending'); expect(node('remake-close') !== null).toBe(state === 'pending');
  await act(async () => node(state === 'pending' ? 'remake-recover' : 'remake-acknowledge').click());
  expect(state === 'pending' ? recovery.recover : recovery.acknowledge).toHaveBeenCalledTimes(1);
});
test('offline recovery keeps metadata visible with disabled mutation controls', async () => {
  props.isOnline = false; recovery.record = { parent_id: 'parent', client_operation_id: 'operation_remake_0001', receipt: null }; await render(true);
  expect(node('remake-recovery-panel')).not.toBeNull(); expect(node('remake-retry').disabled).toBe(true); expect(node('remake-close').disabled).toBe(true);
});
