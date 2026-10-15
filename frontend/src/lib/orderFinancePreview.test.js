import { buildFinancialCreateDraft, canonicalApiBase, parseProductsRon, validateCreatePreview,
  validateFinanceCapabilities, validateFinanceTariffs } from './orderFinancePreview';
import { normalizeCreateOrder } from './orderCreationRecovery';

const form = { restaurant_id: 'r', customer_name: 'Synthetic Customer', customer_phone: '0700000000', customer_address: 'Synthetic Street',
  customer_latitude: 0, customer_longitude: 1, items: [{ name: '', quantity: 1, price: 0 }], total_amount: 999,
  delivery_fee: 999, delivery_zone_id: 'z', payment_type: 'CASH', notes: 'note', source: 'S' };
const draft = () => buildFinancialCreateDraft(form, '12,34', 'v1', normalizeCreateOrder);
const preview = () => ({ contract_version: 1, kind: 'create', informational: true, fingerprint_scope: 'server_key_v1', quote_fingerprint: 'a'.repeat(64),
  actor_id: 'actor', restaurant_id: 'r', parent_order_id: null, parent_order_version: null, currency: 'RON', tariff_version: 'v1', products_bani: 1234,
  collection_mode: 'cash', client_collection_bani: 1234, restaurant_transport_bani: 1600, courier_remuneration_bani: 975, advance_required_bani: 1234,
  advance_paid_bani: null, refund_due_bani: null, refund_paid_bani: null, basis: 'zone', zone_id: 'z', zone_name: 'Zone', zone_sector: null, zone_level: null });
test.each([['0', 0], [' 0 ', 0], ['0,01', 1], ['0.01', 1], ['12.3', 1230], ['0012,34', 1234], ['1000000,00', 100000000]])('exact text money %j', (raw, bani) => expect(parseProductsRon(raw)).toBe(bani));
test.each(['', ' ', '-1', '+1', '1.000', '0.001', '.5', '1.', '1e2', '1,2.3', '1 000', '1000000.01', 'Infinity', null, 0, true, '1'.repeat(33)])('invalid text never becomes zero %j', (raw) => expect(() => parseProductsRon(raw)).toThrow());
test('manual items and all contact/location/source/notes survive; fee never enters financial draft', () => {
  const value = draft(); expect(value.order).toMatchObject({ items: [], customer_latitude: 0, customer_longitude: 1, source: 'S', notes: 'note', total_amount: 12.34, subtotal_amount: 12.34 });
  expect(value.order).not.toHaveProperty('delivery_fee'); expect(value.order).not.toHaveProperty('delivery_zone_id');
  expect(value.financial).toEqual({ contract_version: 1, tariff_version: 'v1', products_bani: 1234, basis: 'zone', zone_id: 'z' });
});
test('no arbitrary tariff default', () => expect(() => buildFinancialCreateDraft(form, '0', '', normalizeCreateOrder)).toThrow());
test.each(['actor_id', 'restaurant_id', 'tariff_version', 'zone_id', 'products_bani', 'advance_required_bani', 'collection_mode', 'quote_fingerprint', 'snapshot_digest'])('preview rejects bad %s', (key) => {
  const data = { ...preview(), [key]: key.includes('bani') ? 0 : 'wrong' };
  expect(() => validateCreatePreview({ status: 200, data }, 'actor', draft())).toThrow();
});
test('valid preview preserves explicit null payment evidence and private admin remuneration', () => {
  expect(validateCreatePreview({ status: 200, data: preview() }, 'actor', draft())).toEqual(preview());
});
test('CARD has zero collection even with nonzero products', () => {
  const data = { ...preview(), collection_mode: 'prepaid', client_collection_bani: 0, advance_required_bani: 0 };
  const value = draft(); value.order.payment_type = 'CARD';
  expect(validateCreatePreview({ status: 200, data }, 'actor', value).products_bani).toBe(1234);
});
test('capability errors do not become marker false', () => {
  const data = { contract_version: 1, actor_id: 'actor', restaurant_id: 'r', finance_enabled: false,
    create_quote_enabled: false, remake_quote_enabled: false, quote_informational: true, supported_basis: ['zone'] };
  expect(validateFinanceCapabilities({ status: 200, data }, 'actor', 'r').finance_enabled).toBe(false);
  expect(() => validateFinanceCapabilities({ status: 503, data }, 'actor', 'r')).toThrow();
  expect(() => validateFinanceCapabilities({ status: 200, data: { ...data, finance_enabled: 'false' } }, 'actor', 'r')).toThrow();
});
test('tariff list is explicit and duplicate versions fail closed', () => {
  const data = { contract_version: 1, actor_id: 'actor', restaurant_id: 'r', tariffs: [{ version: 'v2', currency: 'RON', zone_ids: ['z'] }, { version: 'v1', currency: 'RON', zone_ids: ['z'] }] };
  expect(validateFinanceTariffs({ status: 200, data }, 'actor', 'r').tariffs.map((v) => v.version)).toEqual(['v2', 'v1']);
  data.tariffs.push(data.tariffs[0]); expect(() => validateFinanceTariffs({ status: 200, data }, 'actor', 'r')).toThrow();
});
test('API context includes normalized origin and base path', () => expect(canonicalApiBase('https://EXAMPLE.invalid:443/prefix/')).toBe('https://example.invalid/prefix'));
test.each(['https://u:p@example.invalid', 'https://example.invalid/?x=1', 'https://example.invalid/#x', 'file:///data'])('API base rejects credentials/query/hash/scheme %s', (value) => expect(() => canonicalApiBase(value)).toThrow());
