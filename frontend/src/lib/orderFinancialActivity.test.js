import { readFinancialActivity, financialEventEligibility, financialPickupBlocked } from "./orderFinancialActivity";
import { parseOrderPage } from "./orderReads";

const actor = { id:"user",role:"driver",driver_id:"driver" };
const order = () => ({id:"order",restaurant_id:"restaurant",driver_id:"driver",status:"ACCEPTED",order_version:3,payment_type:"CASH",financial_contract_version:1,
  financial:{contract_version:1,currency:"RON",collection_mode:"cash",products_bani:6530,client_collection_bani:6530,restaurant_transport_bani:1700,courier_remuneration_bani:900,
    advance_required_bani:6530,advance_paid_bani:null,refund_due_bani:null,refund_paid_bani:null,tariff_version:"v1",restaurant_id:"restaurant",basis:"zone",snapshot_at:"2026-10-14T08:00:00Z",snapshot_digest:"a".repeat(64)}});
const activity = (status="declared") => ({contract_version:1,status,driver_id:"driver",declared_unpaid_bani:6530,declaration_id:"f29deeb5-e7a7-4b3e-9f13-f2408365858a",approval_id:status==="declared"?null:"fba29f11-e634-4ee2-8c66-f18a9c04519c",
  declared_at:"2026-10-14T08:00:00Z",approved_at:status==="declared"?null:"2026-10-14T08:01:00Z",picked_up_at:status==="outstanding"?"2026-10-14T08:02:00Z":null,
  outstanding_bani:status==="outstanding"?6530:null,repayment_due_policy:status==="outstanding"?"next_pickup_else_shift_end":null});
const evidence = (value) => ({financial_activity:value,financial_activity_contract_version:1});
test("only absence means no declaration; present null/undefined invalid blocks pickup",()=>{
  expect(readFinancialActivity(order()).state).toBe("none"); expect(financialPickupBlocked(order())).toBe(false);
  for(const value of [null,undefined,{},false,[],"unpaid"]) {const item={...order(),financial_activity:value};expect(readFinancialActivity(item).state).toBe("invalid");expect(financialPickupBlocked(item)).toBe(true);expect(financialEventEligibility(item,actor)).toBeNull();}
});
test.each(["declared","approved","outstanding"])("%s preserves exact amount and quote evidence remains unknown",status=>{
  const item={...order(),...evidence(activity(status)),...(status==="outstanding"?{status:"PICKED_UP",picked_up_at:activity(status).picked_up_at}:{})};expect(readFinancialActivity(item).state).toBe("ready");expect(item.financial.advance_paid_bani).toBeNull();expect(financialPickupBlocked(item)).toBe(status==="declared");
});
test("declaration and approval actors are tenant/driver restricted and use full exact amount",()=>{
  expect(financialEventEligibility(order(),actor)).toEqual({event_type:"advance_not_paid_declared",amount_bani:6530,declaration_id:null});
  expect(financialEventEligibility(order(),{...actor,driver_id:"other"})).toBeNull();
  const item={...order(),...evidence(activity())};
  expect(financialEventEligibility(item,{id:"restaurant-user",role:"restaurant",restaurant_id:"restaurant"})).toEqual({event_type:"advance_shortfall_acknowledged",amount_bani:6530,declaration_id:activity().declaration_id});
  expect(financialEventEligibility(item,{id:"restaurant-user",role:"restaurant",restaurant_id:"foreign"})).toBeNull();expect(financialEventEligibility(item,actor)).toBeNull();
});
test.each([{payment_type:"CARD"},{financial_contract_version:null},{order_version:null},{order_version:3.5},{status:"PICKED_UP"},{read_actions_unavailable:true},{read_data_invalid:true}])("ineligible row %p cannot admit",patch=>expect(financialEventEligibility({...order(),...patch},actor)).toBeNull());
test.each([{driver_id:"foreign"},{declared_unpaid_bani:6531},{declared_unpaid_bani:"6530"},{declared_unpaid_bani:0},{approval_id:activity("approved").approval_id},{approved_at:"2026-10-14T08:01:00Z"},{outstanding_bani:6530},{repayment_due_policy:"next_pickup_else_shift_end"},{contract_version:2},{declaration_id:"bad"},{declared_at:"2026-02-30T08:00:00Z"},{declared_at:"0000-01-01T08:00:00Z"},{private_token:"never-display"}])("malformed declaration %p fails closed",patch=>{
  expect(readFinancialActivity({...order(),...evidence({...activity(),...patch})}).state).toBe("invalid");
});
test("approved and outstanding inconsistent lineage/times/amounts fail closed",()=>{
  for(const patch of [{approval_id:null},{approved_at:null},{approved_at:"2026-10-14T07:00:00Z"},{picked_up_at:"2026-10-14T08:02:00Z"}]) expect(readFinancialActivity({...order(),...evidence({...activity("approved"),...patch})}).state).toBe("invalid");
  for(const patch of [{outstanding_bani:6500},{repayment_due_policy:null},{picked_up_at:null},{picked_up_at:"2026-10-14T08:00:30Z"}]) expect(readFinancialActivity({...order(),status:"PICKED_UP",picked_up_at:activity("outstanding").picked_up_at,...evidence({...activity("outstanding"),...patch})}).state).toBe("invalid");
});
test("read serializer retains public evidence and rejects private/malformed activity without inventing missing rows",()=>{
  const page=items=>({items,next_cursor:null,has_more:false,limit:25,data_warnings:[]});
  const clean=parseOrderPage(page([order()]));expect(Object.hasOwn(clean.items[0],"financial_activity")).toBe(false);
  const valid=parseOrderPage(page([{...order(),...evidence(activity())}]));expect(valid.items[0].financial_activity).toEqual(activity());expect(valid.items[0].financial_activity_contract_version).toBe(1);
  const invalid=parseOrderPage(page([{...order(),financial_activity:null}]));expect(invalid.items[0].read_actions_unavailable).toBe(true);expect(invalid.data_warnings).toContain("INVALID_FINANCIAL_ACTIVITY");
});
test.each([undefined,null,true,"1",0,2])("missing/invalid top activity marker %p fails closed even with valid projection",marker=>{
  const item={...order(),financial_activity:activity()};if(marker!==undefined)item.financial_activity_contract_version=marker;
  expect(readFinancialActivity(item).state).toBe("invalid");expect(financialPickupBlocked(item)).toBe(true);expect(financialEventEligibility(item,actor)).toBeNull();
});
test("marker-only rows and lifecycle/pickup timestamp mismatches fail closed in reads and pickup",()=>{
  const items=[{...order(),financial_activity_contract_version:1},{...order(),...evidence(activity("outstanding"))},
    {...order(),status:"PICKED_UP",picked_up_at:"2026-10-14T08:03:00Z",...evidence(activity("outstanding"))},
    {...order(),status:"DELIVERED",...evidence(activity("approved"))},{...order(),picked_up_at:"2026-10-14T08:02:00Z",...evidence(activity())}];
  for(const item of items) {expect(readFinancialActivity(item).state).toBe("invalid");expect(financialPickupBlocked(item)).toBe(true);
    const page=parseOrderPage({items:[item],next_cursor:null,has_more:false,limit:25,data_warnings:[]});expect(page.items[0].read_actions_unavailable).toBe(true);expect(page.data_warnings).toContain("INVALID_FINANCIAL_ACTIVITY");}
});
test("approved cancelled evidence is valid; outstanding requires picked-up/delivered exact observed time",()=>{
  expect(readFinancialActivity({...order(),status:"CANCELLED",...evidence(activity("approved"))}).state).toBe("ready");
  const item={...order(),status:"DELIVERED",picked_up_at:activity("outstanding").picked_up_at,...evidence(activity("outstanding"))};expect(readFinancialActivity(item).state).toBe("ready");
  const page=parseOrderPage({items:[item],next_cursor:null,has_more:false,limit:25,data_warnings:[]});expect(page.items[0].financial_activity.status).toBe("outstanding");
});
