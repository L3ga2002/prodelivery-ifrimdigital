/** @jest-environment jsdom */
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { OrderCorrectionDialog, correctionForm, correctionChanges } from './OrderCorrectionDialog';

const order = { id: 'qa-order', restaurant_id: 'qa-restaurant', order_version: 4, status: 'READY',
  customer_name: 'Customer Original', customer_phone: '0712345678', customer_address: 'Original Street 42',
  customer_latitude: 46, customer_longitude: 26, notes: 'Original note' };
const ID = '123e4567-e89b-42d3-a456-426614174000';
const pending = { actor_id: 'admin', order_id: order.id, client_operation_id: ID, expected_order_version: 4, receipt: null };
const recovery = (extra = {}) => ({ capability: { ready: true, enabled: true },
  submit: jest.fn(async () => null), recover: jest.fn(), verifyCapability: jest.fn(),
  refreshForNewAttempt: jest.fn(), acknowledge: jest.fn(), ...extra });
let container, root, props;
async function render(extra = {}) {
  props = { order, open: true, onClose: jest.fn(), recovery: recovery(), isOnline: true, ...extra };
  await act(async () => root.render(<OrderCorrectionDialog {...props} />));
}
const button = (text) => [...document.querySelectorAll('button')].find((b) => b.textContent.includes(text));
const click = async (node) => { await act(async () => node.click()); };
async function input(id, value) {
  const el = document.getElementById(id);
  const descriptor = Object.getOwnPropertyDescriptor(el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, 'value');
  await act(async () => { descriptor.set.call(el, value); el.dispatchEvent(new Event('input', { bubbles: true })); });
}
beforeEach(() => { globalThis.IS_REACT_ACT_ENVIRONMENT = true; container = document.createElement('div'); document.body.append(container); root = createRoot(container); });
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });

test('details expose correction button only for strictly eligible orders', async () => {
  await render(); expect(button('Corecteaza')).toBeDefined();
  for (const extra of [{ order_version: null }, { order_version: Number.MAX_SAFE_INTEGER }, { driver_id: '' }, { customer_longitude: null }, { status: 'ASSIGNED' }, { cancelled_by: '' }, { cancellation_reason: 'cancelled' }]) {
    await render({ order: { ...order, ...extra } }); expect(button('Corecteaza')).toBeUndefined();
  }
});
test('default-disabled capability cannot submit and clearly unavailable', async () => {
  await render({ recovery: recovery({ capability: { ready: true, enabled: false } }) });
  expect(document.body.textContent).toContain('indisponibile'); await click(button('Corecteaza')); await input('edit-customer_name', 'Updated Customer');
  expect(button('Salveaza').disabled).toBe(true); expect(props.recovery.submit).not.toHaveBeenCalled();
});
test('no changes, invalid/loading/offline disable save; only operational fields exist', async () => {
  await render(); await click(button('Corecteaza')); expect(button('Salveaza').disabled).toBe(true);
  await input('edit-customer_name', 'x'); expect(button('Salveaza').disabled).toBe(true);
  await input('edit-customer_name', 'Updated Customer'); expect(button('Salveaza').disabled).toBe(false);
  expect(document.querySelectorAll('input')).toHaveLength(5);
  for (const extra of [{ isOnline: false }, { recovery: recovery({ busy: true }) }, { recovery: recovery({ storageInvalid: true }) },
    { recovery: recovery({ capability: { ready: false, enabled: false }, checkingCapability: true }) }]) {
    props = { ...props, ...extra }; await act(async () => root.render(<OrderCorrectionDialog {...props} />));
    expect(button('Salveaza').disabled).toBe(true);
  }
});
test('address requires explicit clear checkbox; form submits exact operational changes', async () => {
  await render(); await click(button('Corecteaza')); await input('edit-customer_address', 'New Street 99');
  expect(button('Salveaza').disabled).toBe(true);
  await click(document.getElementById('edit-clear-coordinates'));
  expect(button('Salveaza').disabled).toBe(false); await click(button('Salveaza'));
  expect(props.recovery.submit).toHaveBeenCalledWith({ order, changes: { customer_address: 'New Street 99', customer_latitude: null, customer_longitude: null } });
});
test('rejected conflict preserves edits, fresh version does not overwrite form', async () => {
  const r = recovery(); await render({ recovery: r }); await click(button('Corecteaza')); await input('edit-customer_name', 'Operator Draft');
  r.record = { ...pending, receipt: { state: 'rejected', error_code: 'ORDER_VERSION_CONFLICT' } };
  await act(async () => root.render(<OrderCorrectionDialog {...props} />));
  expect(document.getElementById('edit-customer_name').value).toBe('Operator Draft');
  r.refreshForNewAttempt.mockImplementation(async () => { delete r.record; return { ...order, customer_name: 'Concurrent Name', customer_address: 'Concurrent Address 90', order_version: 9 }; });
  await click(button('Reincarca'));
  expect(document.getElementById('edit-customer_name').value).toBe('Operator Draft');
  expect(document.getElementById('edit-customer_address').value).toBe('Concurrent Address 90');
  expect(document.body.textContent).toContain('versiunea 9'); await click(button('Salveaza'));
  expect(r.submit.mock.calls[0][0].order.order_version).toBe(9);
  expect(r.submit.mock.calls[0][0].changes).toEqual({ customer_name: 'Operator Draft' });
});
test('reload pending without live order recovers despite disabled marker; form locked', async () => {
  const r = recovery({ record: pending, capability: { ready: true, enabled: false } });
  await render({ order: null, recovery: r }); expect(document.body.textContent).toContain('qa-order');
  await click(button('Verifica aceeasi')); expect(r.recover).toHaveBeenCalledTimes(1);
  expect(button('Salveaza')).toBeUndefined(); expect(document.querySelector('fieldset').disabled).toBe(true);
});
test('reloaded rejected draft restores only saved changes after explicit refresh', async () => {
  const r = recovery({ record: { ...pending, receipt: { state: 'rejected', error_code: 'ORDER_VERSION_CONFLICT' } },
    draft: { ...pending, changes: { notes: 'Saved Private Note' } } });
  r.refreshForNewAttempt.mockImplementation(async () => { delete r.record; delete r.draft; return { ...order, order_version: 10 }; });
  await render({ order: null, recovery: r }); await click(button('Reincarca'));
  expect(document.getElementById('edit-customer_name').value).toBe(order.customer_name);
  expect(document.getElementById('edit-notes').value).toBe('Saved Private Note');
  await click(button('Salveaza'));
  expect(r.submit.mock.calls[0][0].changes).toEqual({ notes: 'Saved Private Note' });
});
test('helper validates coordinate pair rather than trusting string inputs', () => {
  const form = correctionForm(order);
  expect(() => correctionChanges(order, { ...form, latitude: 'not-number' })).toThrow();
  expect(() => correctionChanges(order, { ...form, latitude: '' })).toThrow();
  expect(correctionChanges(order, { ...form, latitude: '0', longitude: '0' })).toEqual({ customer_latitude: 0, customer_longitude: 0 });
});
