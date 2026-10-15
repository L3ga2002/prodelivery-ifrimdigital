import { act, StrictMode } from "react";
import { createRoot } from "react-dom/client";
import axios from "axios";
import { useOrderFinancialEventRecovery } from "./useOrderFinancialEventRecovery";
import { FinancialEventRecoveryPanel, FinancialEventControls, OrderFinancialActivitySummary } from "../components/OrderFinancialActivity";
jest.mock("axios",()=>({create:jest.fn()}));
const actor={id:"user",role:"driver",driver_id:"driver"}, ID="f29deeb5-e7a7-4b3e-9f13-f2408365858a", DECL="af4373a2-4f78-4a1b-9889-ea59627d644f";
const key="prodelivery:order-financial-event:v1:user:driver:driver";
const order=()=>({id:"order",restaurant_id:"restaurant",driver_id:"driver",status:"ACCEPTED",order_version:3,payment_type:"CASH",financial_contract_version:1,
  financial:{contract_version:1,currency:"RON",collection_mode:"cash",products_bani:6530,client_collection_bani:6530,restaurant_transport_bani:1700,courier_remuneration_bani:900,advance_required_bani:6530,advance_paid_bani:null,refund_due_bani:null,refund_paid_bani:null,tariff_version:"v1",restaurant_id:"restaurant",basis:"zone",snapshot_at:"2026-10-14T08:00:00Z",snapshot_digest:"a".repeat(64)}});
const activity=(status="declared")=>({contract_version:1,status,driver_id:"driver",declared_unpaid_bani:6530,declaration_id:DECL,approval_id:status==="declared"?null:ID,declared_at:"2026-10-14T08:00:00Z",approved_at:status==="declared"?null:"2026-10-14T08:01:00Z",picked_up_at:status==="outstanding"?"2026-10-14T08:02:00Z":null,outstanding_bani:status==="outstanding"?6530:null,repayment_due_policy:status==="outstanding"?"next_pickup_else_shift_end":null});
const stored={version:1,actor_id:"user",role:"driver",resource_id:"driver",order_id:"order",event_type:"advance_not_paid_declared",amount_bani:6530,declaration_id:null,client_operation_id:ID,expected_order_version:3,receipt:null};
const receipt=(state="pending")=>({status:state==="pending"?202:200,headers:{"retry-after":"2"},data:{client_operation_id:ID,state,order_id:state==="pending"?null:"order",order_version:state==="pending"?null:4,error_code:null,retry_after_seconds:state==="pending"?2:null}});
const missing=()=>Object.assign(new Error("404"),{response:{status:404,data:{detail:{code:"OPERATION_NOT_FOUND"}}}});
const deferred=()=>{let resolve;const promise=new Promise(yes=>{resolve=yes;});return {promise,resolve};};
let root,container,view,transport,callback;
const Probe=({user=actor,token="qa-token",online=true,item=order(),override})=>{
  view=useOrderFinancialEventRecovery(user,"https://qa.invalid",online,token);
  return <><FinancialEventRecoveryPanel recovery={{...view,...override}} isOnline={online} onAcknowledged={callback}/><FinancialEventControls order={item} actor={user} recovery={view} isOnline={online}/><OrderFinancialActivitySummary order={item}/></>;
};
const render=(props={},strict=false)=>act(async()=>root.render(strict?<StrictMode><Probe {...props}/></StrictMode>:<Probe {...props}/>));
const flush=()=>act(async()=>{await Promise.resolve();await Promise.resolve();await Promise.resolve();});
const event=(name,persisted=true)=>act(async()=>{const e=new Event(name);Object.defineProperty(e,"persisted",{value:persisted});window.dispatchEvent(e);});
const button=text=>[...container.querySelectorAll("button")].find(node=>node.textContent===text);
beforeEach(()=>{
  globalThis.IS_REACT_ACT_ENVIRONMENT=true;jest.clearAllMocks();window.localStorage.clear();
  Object.defineProperty(navigator,"locks",{configurable:true,value:{request:jest.fn(async(_k,_o,cb)=>cb({}))}});
  Object.defineProperty(window,"crypto",{configurable:true,value:{randomUUID:()=>ID}});
  transport={get:jest.fn(async path=>path.endsWith("auth/me")?{status:200,data:actor}:path.endsWith("capabilities")?{status:200,data:{financial_event_recovery_enabled:true}}:path.endsWith("/order")?{status:200,data:{...order(),order_version:4,financial_activity:activity(),financial_activity_contract_version:1}}:receipt()),post:jest.fn(async()=>receipt("applied"))};
  axios.create.mockReturnValue(transport);callback=jest.fn();container=document.createElement("div");document.body.append(container);root=createRoot(container);
});
afterEach(async()=>{await act(async()=>root.unmount());container.remove();});
test("capability default off hides mutation control and no event is sent",async()=>{
  transport.get.mockResolvedValue({status:200,data:{financial_event_recovery_enabled:false}});await render();await flush();expect(button("Nu am achitat — numerar insuficient")).toBeUndefined();expect(transport.post).not.toHaveBeenCalled();
});
test("enabled eligible driver sees fully-unpaid declaration; legacy/CARD/foreign see none",async()=>{
  await render();await flush();expect(button("Nu am achitat — numerar insuficient")).toBeDefined();expect(container.textContent).toContain("nu ai achitat nimic");
  for(const item of [{id:"legacy",status:"ACCEPTED",total_amount:50},{...order(),payment_type:"CARD"},{...order(),driver_id:"foreign"}]) {await render({item});expect(button("Nu am achitat — numerar insuficient")).toBeUndefined();}
});
test("pending reload and reconnect only look up; resume explicit and bodyless",async()=>{
  window.localStorage.setItem(key,JSON.stringify(stored));await render();await flush();expect(button("Continuă încercarea")).toBeDefined();expect(transport.post).not.toHaveBeenCalled();
  await render({online:false});expect(button("Continuă încercarea").disabled).toBe(true);expect(container.textContent).toContain("Fără internet");await render({online:true});await flush();expect(transport.post).not.toHaveBeenCalled();
  await act(async()=>button("Continuă încercarea").click());expect(transport.post).toHaveBeenCalledTimes(1);expect(transport.post.mock.calls[0][1]).toBeUndefined();
});
test("StrictMode missing lookup exposes same-id resend without automatic mutation",async()=>{
  window.localStorage.setItem(key,JSON.stringify(stored));transport.get.mockRejectedValue(missing());await render({},true);await flush();expect(button("Retrimite aceeași încercare")).toBeDefined();expect(transport.post).not.toHaveBeenCalled();
  await act(async()=>button("Retrimite aceeași încercare").click());expect(transport.post).toHaveBeenCalledTimes(1);expect(transport.post.mock.calls[0][1].client_operation_id).toBe(ID);
});
test("two synchronous submits produce one POST and one durable identity",async()=>{
  await render();await flush();const gate=deferred();transport.post.mockReturnValue(gate.promise);let first,second;
  await act(async()=>{first=view.submit({order:order()});second=view.submit({order:order()});});expect(await second).toBeNull();expect(transport.post).toHaveBeenCalledTimes(1);
  await act(async()=>{gate.resolve(receipt("applied"));await first;});expect(view.record.client_operation_id).toBe(ID);
});
test("actor switch hides initial intention and fences old late receipt",async()=>{
  const gate=deferred();window.localStorage.setItem(key,JSON.stringify(stored));transport.get.mockReturnValue(gate.promise);await render();await render({user:{...actor,id:"other",driver_id:"other-driver"}});
  expect(container.textContent).not.toContain("Comanda order");await act(async()=>gate.resolve(receipt("replayed")));expect(view.record).toBeNull();expect(JSON.parse(window.localStorage.getItem(key)).receipt).toBeNull();expect(transport.post).not.toHaveBeenCalled();
});
test("token rotation retains original record and cookie-only transport clears bearer",async()=>{
  window.localStorage.setItem(key,JSON.stringify(stored));await render();await render({token:null});await flush();expect(view.record.client_operation_id).toBe(ID);expect(transport.get.mock.calls.at(-1)[1].headers).toEqual({Authorization:null,"X-Expected-Actor-ID":"user"});expect(transport.post).not.toHaveBeenCalled();
});
test("BFCache requires exact resource binding and correct restoration is read-only",async()=>{
  window.localStorage.setItem(key,JSON.stringify(stored));await render();await event("pagehide");expect(view.sessionSuspended).toBe(true);
  transport.get.mockImplementation(async path=>path.endsWith("auth/me")?{status:200,data:{...actor,driver_id:"rebound"}}:receipt());await event("pageshow");expect(view.sessionSuspended).toBe(true);expect(view.errorCode).toBe("SESSION_CHANGED");
  transport.get.mockImplementation(async path=>path.endsWith("auth/me")?{status:200,data:actor}:receipt());await act(async()=>view.revalidateSession());expect(view.sessionSuspended).toBe(false);expect(transport.post).not.toHaveBeenCalled();
});
test("unmount/pagehide while POST in flight preserves pending bytes and suppresses late result",async()=>{
  await render();await flush();const gate=deferred();transport.post.mockReturnValue(gate.promise);let flight;await act(async()=>{flight=view.submit({order:order()});});await event("pagehide",false);
  await act(async()=>{gate.resolve(receipt("applied"));await flight;});expect(JSON.parse(window.localStorage.getItem(key)).receipt).toBeNull();expect(view.sessionSuspended).toBe(true);
});
test("late acknowledge callback after actor switch cannot update new account",async()=>{
  const gate=deferred();window.localStorage.setItem(key,JSON.stringify({...stored,receipt:receipt("applied").data}));await render({override:{acknowledge:()=>gate.promise}});
  await act(async()=>button("Am văzut rezultatul și reîncarc comanda").click());await render({user:{...actor,id:"other",driver_id:"other-driver"}});
  await act(async()=>gate.resolve({...order(),order_version:4,financial_activity:activity(),financial_activity_contract_version:1}));expect(callback).not.toHaveBeenCalled();
});
test("restaurant approval visible only for exact declared own restaurant, no payment button",async()=>{
  const user={id:"restaurant-user",role:"restaurant",restaurant_id:"restaurant"};await render({user,item:{...order(),financial_activity:activity(),financial_activity_contract_version:1}});await flush();expect(button("Aprob ridicarea fără plată")).toBeDefined();expect(container.textContent).toContain("nu confirmă o plată");
  await act(async()=>button("Aprob ridicarea fără plată").click());expect(transport.post.mock.calls[0][1]).toMatchObject({declaration_id:DECL,event_type:"advance_shortfall_acknowledged",amount_bani:6530});
});
test("outstanding summary displays policy and amount while invalid evidence has no active controls",async()=>{
  await render({item:{...order(),status:"PICKED_UP",picked_up_at:activity("outstanding").picked_up_at,financial_activity:activity("outstanding"),financial_activity_contract_version:1}});expect(container.textContent).toContain("65,30 RON");expect(container.textContent).toContain("la finalul programului");expect(container.textContent).toContain("nu confirmă primirea banilor");
  await render({item:{...order(),financial_activity:null}});expect(container.querySelector('[data-testid="financial-activity-invalid"]')).not.toBeNull();expect(button("Nu am achitat — numerar insuficient")).toBeUndefined();
});
