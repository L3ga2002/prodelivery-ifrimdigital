import { buildRemakeDraft, parseRemakeUnitPrice, pureLegacyRemake, validateRemakeParent, validateRemakePreview,
  validateRemakeReceipt, validateRemakeReadback, assertNoOriginalFinancialIntent } from './orderRemakeFinance';

const actor = { id: 'owner', role: 'restaurant', restaurant_id: 'r1' };
const parent = () => ({ contract_version: 1, kind: 'remake_parent', actor_id: 'owner', actor_role: 'restaurant', restaurant_id: 'r1',
  parent: { order_id: 'parent', order_version: 4, status: 'DELIVERED', source: 'S', customer_name: 'Private Customer', customer_phone: '0700011223',
    customer_address: 'Private Street 123', customer_latitude: 0, customer_longitude: 0, has_problem_followup: false, problem_followup_order_id: null,
    delivery_zone_id: 'z1', delivery_zone_name: 'Zone', delivery_sector: null, delivery_zone_level: 0 }, eligibility: { can_preview: true, blocking_code: null } });
const form = () => ({ problem_type: 'missing_product', item_name: 'Replacement', quantity: '2', unit_price: '13,05', description: 'Explicit replacement', payment_type: 'CASH' });
const financial = () => ({ contract_version: 1, currency: 'RON', tariff_version: 'v1', products_bani: 2610, collection_mode: 'cash', client_collection_bani: 2610,
  restaurant_transport_bani: 1600, advance_required_bani: 2610, advance_paid_bani: null, refund_due_bani: null, refund_paid_bani: null,
  basis: 'zone', zone_id: 'z1', zone_name: 'Zone', zone_sector: null, zone_level: 0 });
const preview = () => ({ ...financial(), kind: 'remake', informational: true, fingerprint_scope: 'server_key_v1', quote_fingerprint: 'a'.repeat(64),
  actor_id: 'owner', restaurant_id: 'r1', parent_order_id: 'parent', parent_order_version: 4 });
const record = () => ({ actor_id: 'owner', actor_role: 'restaurant', restaurant_id: 'r1', parent_id: 'parent', expected_order_version: 4,
  client_operation_id: 'operation_remake_0001', quote_confirmation: { contract_version: 1, quote_fingerprint: 'a'.repeat(64) } });
const receipt = () => ({ client_operation_id: 'operation_remake_0001', state: 'replayed', order_id: 'child', order_version: 0,
  parent_order_id: 'parent', parent_order_version: 5, error_code: null, retry_after_seconds: null });
const readback = () => ({ contract_version: 1, kind: 'remake_readback', actor_id: 'owner', actor_role: 'restaurant', restaurant_id: 'r1',
  client_operation_id: record().client_operation_id, quote_confirmation: record().quote_confirmation, receipt: receipt(),
  parent: { order_id: 'parent', order_version: 8, status: 'DELIVERED', has_problem_followup: true, problem_followup_order_id: 'child' },
  child: { order_id: 'child', order_version: 3, status: 'DELIVERED', linked_problem_order_id: 'parent', creation_kind: 'remake', source: 'S', payment_type: 'CASH' }, financial: financial() });

test.each(['', ' ', null, 0, '-1', '+1', '1e2', '.5', '1.234', 'Infinity', 'NaN', '100000.01'])('rejects non-explicit or inexact unit price %p', (value) => {
  expect(() => parseRemakeUnitPrice(value)).toThrow();
});
test.each([['0', 0], ['0,00', 0], ['13.05', 1305], [' 13,05 ', 1305], ['100000', 10000000]])('parses exact raw money %s', (value, expected) => {
  expect(parseRemakeUnitPrice(value)).toBe(expected);
});
test.each(['CASH', 'CARD'])('one draft controls preview and submission for %s', (payment) => {
  const draft = buildRemakeDraft(parent(), { ...form(), payment_type: payment }, 'v1');
  expect(draft.financial.products_bani).toBe(2610); expect(draft.items[0].unit_price_bani).toBe(1305);
  expect(draft.client_collection_bani).toBe(payment === 'CASH' ? 2610 : 0); expect(draft.advance_required_bani).toBe(draft.client_collection_bani);
  expect(draft.collection_basis).toBe(payment === 'CASH' ? 'new_receipt' : 'prepaid_new_order');
  expect(draft).not.toHaveProperty('client_operation_id'); expect(draft).not.toHaveProperty('quote_confirmation');
});
test.each([{ quantity: '0' }, { quantity: '1.5' }, { quantity: '101' }, { quantity: 1 }, { payment_type: '' }, { unit_price: '' },
  { quantity: '100', unit_price: '100000' }, { description: 'x' }, { item_name: '' }])('invalid draft never defaults %p', (changes) => {
  expect(() => buildRemakeDraft(parent(), { ...form(), ...changes }, 'v1')).toThrow();
});
test('explicit zero is valid and no arbitrary tariff is selected', () => {
  expect(buildRemakeDraft(parent(), { ...form(), unit_price: '0' }, 'v1').financial.products_bani).toBe(0);
  expect(() => buildRemakeDraft(parent(), form(), '')).toThrow();
  const p = parent(); p.parent.delivery_zone_id = null; expect(() => buildRemakeDraft(p, form(), 'v1')).toThrow();
});
test.each(['order_version', 'financial', 'financial_contract_version', 'financial_activity', 'financial_activity_contract_version', 'custody_activity', 'custody_contract_version', 'read_actions_unavailable'])('own marker %s never downgrades even null', (key) => {
  expect(pureLegacyRemake({ id: 'parent', [key]: null })).toBe(false); expect(pureLegacyRemake({ id: 'parent' })).toBe(true);
});
test.each(['courier_remuneration_bani', 'tariff_rule', 'snapshot_digest', 'financial', 'extra'])('private preview field %s fails closed', (field) => {
  expect(() => validateRemakePreview({ status: 200, data: { ...preview(), [field]: 1 } }, 'owner', 'r1', 'parent', buildRemakeDraft(parent(), form(), 'v1'))).toThrow();
});
test.each(['actor_id', 'restaurant_id', 'parent_order_id', 'tariff_version', 'zone_id'])('quote mismatch %s fails closed', (field) => {
  expect(() => validateRemakePreview({ status: 200, data: { ...preview(), [field]: 'foreign' } }, 'owner', 'r1', 'parent', buildRemakeDraft(parent(), form(), 'v1'))).toThrow();
});
test('parent version is safe integer and zero coordinates survive', () => {
  expect(validateRemakeParent({ status: 200, data: parent() }, actor, 'parent').parent.customer_latitude).toBe(0);
  const p = parent(); p.parent.order_version = Number.MAX_SAFE_INTEGER + 1;
  expect(() => validateRemakeParent({ status: 200, data: p }, actor, 'parent')).toThrow();
});
test.each(Object.keys(receipt()))('receipt requires each of eight fields: %s', (field) => {
  const data = receipt(); delete data[field]; expect(() => validateRemakeReceipt({ status: 200, data }, record())).toThrow();
});
test('public readback accepts advanced versions and exact new amounts', () => {
  expect(validateRemakeReadback({ status: 200, data: readback() }, record(), receipt(), null).child.order_version).toBe(3);
  expect(validateRemakeReadback({ status: 200, data: readback() }, record(), receipt(), { preview: preview(), command: { payment_type: 'CASH' }, parent_context: parent() }).financial.products_bani).toBe(2610);
});
test.each(['courier_remuneration_bani', 'snapshot_digest', 'operation_ref'])('readback refuses private material %s', (field) => {
  const value = readback(); value.financial[field] = 1; expect(() => validateRemakeReadback({ status: 200, data: value }, record(), receipt(), null)).toThrow();
});
test('fresh original finance guard blocks same parent and corrupt storage without changes', () => {
  const value = { version: 1, actor_id: 'owner', role: 'restaurant', resource_id: 'r1', order_id: 'parent', event_type: 'advance_shortfall_acknowledged',
    amount_bani: 10, declaration_id: '11111111-1111-4111-8111-111111111111', client_operation_id: '22222222-2222-4222-8222-222222222222', expected_order_version: 4, receipt: null };
  const storage = { getItem: jest.fn(() => JSON.stringify(value)), setItem: jest.fn(), removeItem: jest.fn() };
  expect(() => assertNoOriginalFinancialIntent(storage, actor, 'parent')).toThrow();
  expect(() => assertNoOriginalFinancialIntent(storage, actor, 'other')).not.toThrow();
  storage.getItem.mockReturnValue('{'); expect(() => assertNoOriginalFinancialIntent(storage, actor, 'other')).toThrow();
  expect(storage.setItem).not.toHaveBeenCalled(); expect(storage.removeItem).not.toHaveBeenCalled();
});

test.each([false, 0, '', undefined])('falsy or missing foreign-parent financial receipt %p is corrupt', (receipt) => {
  const value = { version: 1, actor_id: 'owner', role: 'restaurant', resource_id: 'r1', order_id: 'foreign', event_type: 'advance_shortfall_acknowledged', amount_bani: 10, declaration_id: '11111111-1111-4111-8111-111111111111', client_operation_id: '22222222-2222-4222-8222-222222222222', expected_order_version: 4, receipt };
  expect(() => assertNoOriginalFinancialIntent({ getItem: () => JSON.stringify(value) }, actor, 'parent')).toThrow();
});
test.each(['read_financial_invalid', 'read_remake_invalid', 'read_custody_invalid', 'read_financial_activity_invalid', '_read_invalid'])('isolated read corruption %s prevents legacy downgrade', (key) => { expect(pureLegacyRemake({ id: 'parent', [key]: false })).toBe(false); });
test.each([undefined, '1', '3', 'invalid'])('pending header %p cannot confirm receipt', (header) => {
  const value = { ...receipt(), state: 'pending', order_id: null, order_version: null, parent_order_id: null, parent_order_version: null, retry_after_seconds: 2 };
  expect(() => validateRemakeReceipt({ status: 202, headers: { 'retry-after': header }, data: value }, record())).toThrow();
  expect(validateRemakeReceipt({ status: 202, headers: { 'retry-after': '2' }, data: value }, record()).state).toBe('pending');
});

const originalFinancialRecord = (receiptState = null) => {
  const id = '22222222-2222-4222-8222-222222222222';
  const applied = ['applied', 'replayed'].includes(receiptState);
  return { version: 1, actor_id: 'owner', role: 'restaurant', resource_id: 'r1', order_id: 'foreign', event_type: 'advance_shortfall_acknowledged',
    amount_bani: 10, declaration_id: '11111111-1111-4111-8111-111111111111', client_operation_id: id, expected_order_version: 4,
    receipt: receiptState === null ? null : { client_operation_id: id, state: receiptState, order_id: applied ? 'foreign' : null,
      order_version: applied ? 5 : null, error_code: receiptState === 'rejected' ? 'FINANCIAL_DECLARATION_CHANGED' : null, retry_after_seconds: receiptState === 'pending' ? 2 : null } };
};
const originalStorage = (value) => ({ getItem: () => JSON.stringify(value), setItem: jest.fn(), removeItem: jest.fn() });
test.each([0, -1, 1.5, 100000001, Number.MAX_SAFE_INTEGER + 1, null, '10', true])('original amount %p must satisfy its own positive-money contract', (amount) => {
  expect(() => assertNoOriginalFinancialIntent(originalStorage({ ...originalFinancialRecord(), amount_bani: amount }), actor, 'parent')).toThrow();
});
test.each(['declaration_id', 'client_operation_id'])('original %s must be UUID, not remake operation syntax', (field) => {
  expect(() => assertNoOriginalFinancialIntent(originalStorage({ ...originalFinancialRecord(), [field]: 'operation_remake_0001' }), actor, 'parent')).toThrow();
});
test.each([null, '', false])('original declaration %p is invalid for restaurant', (value) => {
  expect(() => assertNoOriginalFinancialIntent(originalStorage({ ...originalFinancialRecord(), declaration_id: value }), actor, 'parent')).toThrow();
});
test.each([Number.MAX_SAFE_INTEGER, Number.MAX_SAFE_INTEGER + 1, -1, 1.5, '4', null, false])('original version %p retains strict less-than-safe-max bound', (value) => {
  expect(() => assertNoOriginalFinancialIntent(originalStorage({ ...originalFinancialRecord(), expected_order_version: value }), actor, 'parent')).toThrow();
});
test('original foreign identifier rejects isolated surrogate', () => {
  expect(() => assertNoOriginalFinancialIntent(originalStorage({ ...originalFinancialRecord(), order_id: '\ud800' }), actor, 'parent')).toThrow();
});
test.each(['operation_remake_0001', '33333333-3333-4333-8333-333333333333', null])('original receipt ID %p must match its valid UUID metadata', (value) => {
  const record = originalFinancialRecord('pending'); record.receipt.client_operation_id = value;
  expect(() => assertNoOriginalFinancialIntent(originalStorage(record), actor, 'parent')).toThrow();
});
test.each([null, 'pending', 'applied', 'replayed', 'rejected'])('valid foreign original receipt %p is permitted without mutation, same-parent blocks', (state) => {
  const value = originalFinancialRecord(state), storage = originalStorage(value);
  expect(() => assertNoOriginalFinancialIntent(storage, actor, 'parent')).not.toThrow();
  expect(() => assertNoOriginalFinancialIntent(storage, actor, 'foreign')).toThrow();
  expect(storage.setItem).not.toHaveBeenCalled(); expect(storage.removeItem).not.toHaveBeenCalled();
});
