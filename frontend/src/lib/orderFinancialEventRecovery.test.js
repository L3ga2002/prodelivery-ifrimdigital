import { createOrderFinancialEventRecovery, financialEventRejectionStatus, validateFinancialEventReceipt } from "./orderFinancialEventRecovery";
const ID="f29deeb5-e7a7-4b3e-9f13-f2408365858a", DECL="af4373a2-4f78-4a1b-9889-ea59627d644f";
const actor={id:"user",role:"driver",driver_id:"driver"};
const order=()=>({id:"order",restaurant_id:"restaurant",driver_id:"driver",status:"ACCEPTED",order_version:3,payment_type:"CASH",financial_contract_version:1,
  financial:{contract_version:1,currency:"RON",collection_mode:"cash",products_bani:6530,client_collection_bani:6530,restaurant_transport_bani:1700,courier_remuneration_bani:900,advance_required_bani:6530,advance_paid_bani:null,refund_due_bani:null,refund_paid_bani:null,tariff_version:"v1",restaurant_id:"restaurant",basis:"zone",snapshot_at:"2026-10-14T08:00:00Z",snapshot_digest:"a".repeat(64)}});
const activity=()=>({contract_version:1,status:"declared",driver_id:"driver",declared_unpaid_bani:6530,declaration_id:DECL,approval_id:null,declared_at:"2026-10-14T08:00:00Z",approved_at:null,picked_up_at:null,outstanding_bani:null,repayment_due_policy:null});
const receipt=(state="applied",code=null)=>({status:state==="pending"?202:state==="rejected"?financialEventRejectionStatus[code]:200,headers:{"retry-after":"2"},data:{client_operation_id:ID,state,order_id:["applied","replayed"].includes(state)?"order":null,order_version:["applied","replayed"].includes(state)?4:null,error_code:code,retry_after_seconds:state==="pending"?2:null}});
const missing=()=>Object.assign(new Error("404"),{response:{status:404,data:{detail:{code:"OPERATION_NOT_FOUND"}}}});
const deferred=()=>{let resolve;const promise=new Promise(yes=>{resolve=yes;});return {promise,resolve};};
let api, storage, values, controller, locks, online, uuid;
const make=(who=actor)=>createOrderFinancialEventRecovery({actor:who,api,durableStorage:storage,locks,crypto:{randomUUID:uuid},isOnline:()=>online});
beforeEach(()=>{
  online=true;values=new Map();storage={getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};
  locks={request:jest.fn(async(_k,_o,cb)=>cb({}))};uuid=jest.fn(()=>ID);
  api={get:jest.fn(async path=>path.endsWith("capabilities")?{status:200,data:{financial_event_recovery_enabled:true}}:path.endsWith("/order")?{status:200,data:{...order(),order_version:4,financial_activity:activity(),financial_activity_contract_version:1}}:receipt("replayed")),post:jest.fn(async()=>receipt())};controller=make();
});
test("durable full unpaid command is saved before POST and contains no customer/token/quote snapshot",async()=>{
  api.post.mockImplementation(async(_path,body)=>{expect(controller.snapshot().client_operation_id).toBe(ID);expect(body).toEqual({client_operation_id:ID,expected_order_version:3,event_type:"advance_not_paid_declared",amount_bani:6530,declaration_id:null});return receipt();});
  await controller.submit({order:{...order(),customer_name:"PRIVATE CUSTOMER",customer_address:"SECRET STREET"}});
  const saved=[...values.values()][0];expect(saved).not.toContain("PRIVATE");expect(saved).not.toContain("SECRET");expect(saved).not.toContain("snapshot_digest");expect(controller.snapshot().receipt.state).toBe("applied");
});
test("lost ACK looks up same identity; reload lookup never POSTs automatically",async()=>{
  api.post.mockRejectedValue(new Error("lost ack"));expect((await controller.submit({order:order()})).state).toBe("replayed");expect(api.post).toHaveBeenCalledTimes(1);expect(uuid).toHaveBeenCalledTimes(1);
  controller=make();await controller.recover();expect(api.post).toHaveBeenCalledTimes(1);expect(controller.snapshot().client_operation_id).toBe(ID);
});
test("lookup missing admits only explicit same-id resend, not new submit",async()=>{
  api.post.mockRejectedValue(new Error("lost"));api.get.mockImplementation(async path=>path.endsWith("capabilities")?{status:200,data:{financial_event_recovery_enabled:true}}:Promise.reject(missing()));
  expect(await controller.submit({order:order()})).toEqual({not_admitted:true});expect(api.post).toHaveBeenCalledTimes(1);
  await expect(controller.submit({order:order()})).rejects.toMatchObject({code:"INTENT_PENDING"});controller=make();await controller.recover();expect(api.post).toHaveBeenCalledTimes(1);
  api.post.mockResolvedValue(receipt());await controller.resend();expect(api.post).toHaveBeenCalledTimes(2);expect(api.post.mock.calls[1][1].client_operation_id).toBe(ID);expect(uuid).toHaveBeenCalledTimes(1);
});
test("pending resume reads first, sends bodyless, and works when admissions disabled",async()=>{
  api.post.mockResolvedValue(receipt("pending"));await controller.submit({order:order()});
  api.get.mockResolvedValue(receipt("pending"));api.post.mockResolvedValue(receipt("replayed"));await controller.resume();
  expect(api.post.mock.calls[1][0]).toBe(`/api/orders/operations/financial-event/order/${ID}/resume`);expect(api.post.mock.calls[1][1]).toBeUndefined();
});
test("default off never allocates identity, persists, or mutates",async()=>{
  api.get.mockResolvedValue({status:200,data:{financial_event_recovery_enabled:false}});await expect(controller.submit({order:order()})).rejects.toMatchObject({code:"FINANCIAL_EVENT_DISABLED"});expect(values.size).toBe(0);expect(api.post).not.toHaveBeenCalled();expect(uuid).not.toHaveBeenCalled();
});
test.each(Object.keys(financialEventRejectionStatus))("durable %s rejection is verifiable",async code=>{
  api.post.mockResolvedValue(receipt("rejected",code));expect((await controller.submit({order:order()})).error_code).toBe(code);expect(controller.snapshot().receipt.state).toBe("rejected");
});
test("foreign actor and resource have disjoint stored intents",async()=>{
  await controller.submit({order:order()});expect(make({...actor,id:"other"}).snapshot()).toBeNull();expect(make({...actor,driver_id:"other"}).snapshot()).toBeNull();
});
test("restaurant approval references exact declaration and preserves quote unknown payment",async()=>{
  controller=make({id:"restaurant-user",role:"restaurant",restaurant_id:"restaurant"});await controller.submit({order:{...order(),financial_activity:activity(),financial_activity_contract_version:1}});
  expect(api.post.mock.calls[0][1]).toMatchObject({event_type:"advance_shortfall_acknowledged",declaration_id:DECL,amount_bani:6530});
});
test("same actor cannot submit second order while initial result remains unacknowledged",async()=>{
  await controller.submit({order:order()});await expect(controller.submit({order:{...order(),id:"other-order"}})).rejects.toMatchObject({code:"INTENT_PENDING"});expect(api.post).toHaveBeenCalledTimes(1);
});
test("offline and lock/storage failure prevent mutation",async()=>{
  online=false;await expect(controller.submit({order:order()})).rejects.toMatchObject({code:"OFFLINE"});online=true;
  locks.request.mockImplementation(async(_k,_o,cb)=>cb(null));await expect(controller.submit({order:order()})).rejects.toMatchObject({code:"BUSY"});
  locks.request.mockImplementation(async(_k,_o,cb)=>cb({}));storage.setItem=()=>{throw Error("quota");};await expect(controller.submit({order:order()})).rejects.toMatchObject({code:"STORAGE_UNAVAILABLE"});expect(api.post).not.toHaveBeenCalled();
});
test("malformed stored intent blocks and preserves durable bytes",()=>{
  const key=`prodelivery:order-financial-event:v1:user:driver:driver`;values.set(key,"broken JSON");expect(()=>controller.snapshot()).toThrow();expect(controller.storageBlocked()).toBe(true);expect(values.get(key)).toBe("broken JSON");
});
test("account retirement fences late POST from durable storage and does not create another operation",async()=>{
  const late=deferred(), started=deferred();api.post.mockImplementation(()=>{started.resolve();return late.promise;});const flight=controller.submit({order:order()});await started.promise;
  controller.deactivate();late.resolve(receipt());await expect(flight).rejects.toMatchObject({code:"SESSION_CHANGED"});expect(JSON.parse([...values.values()][0]).receipt).toBeNull();
});
test("admitted stale-version rejection can be acknowledged and refreshed without another UUID or POST",async()=>{
  api.post.mockResolvedValue(receipt("rejected","ORDER_VERSION_CONFLICT"));await controller.submit({order:order()});
  api.get.mockImplementation(async path=>path.endsWith("/order")?{status:200,data:{...order(),order_version:8}}:receipt("rejected","ORDER_VERSION_CONFLICT"));
  expect((await controller.acknowledge()).order_version).toBe(8);expect(values.size).toBe(0);expect(uuid).toHaveBeenCalledTimes(1);expect(api.post).toHaveBeenCalledTimes(1);
});
test("acknowledge proves same receipt then fresh financial activity before clearing",async()=>{
  await controller.submit({order:order()});const fresh=await controller.acknowledge();expect(fresh.order_version).toBe(4);expect(values.size).toBe(0);
});
test("acknowledge malformed/missing/stale evidence keeps original receipt",async()=>{
  await controller.submit({order:order()});for(const patch of [{financial_activity:null},{order_version:3},{driver_id:"foreign"},{financial_activity:undefined}]) {
    api.get.mockImplementation(async path=>path.endsWith("/order")?{status:200,data:{...order(),order_version:4,financial_activity:activity(),financial_activity_contract_version:1,...patch}}:receipt("replayed"));await expect(controller.acknowledge()).rejects.toMatchObject({code:"INVALID_RESPONSE"});expect(controller.snapshot().receipt.state).toBe("applied");
  }
});
test("receipt mismatch/extra fields/incorrect retry header never becomes trusted evidence",()=>{
  const record={client_operation_id:ID,order_id:"order",expected_order_version:3};
  for(const patch of [{order_id:"other"},{order_version:5},{extra:"secret"},{client_operation_id:DECL}]) expect(()=>validateFinancialEventReceipt({...receipt(),data:{...receipt().data,...patch}},record)).toThrow();
  expect(()=>validateFinancialEventReceipt({...receipt("pending"),headers:{}},record)).toThrow();
});
