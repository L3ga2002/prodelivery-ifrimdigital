import { act, StrictMode } from "react";
import { createRoot } from "react-dom/client";
import axios from "axios";
import { useOrderCustodyRecovery } from "./useOrderCustodyRecovery";
import { CustodyRecoveryPanel, CustodyControls, OrderCustodySummary } from "../components/OrderCustody";
jest.mock("axios",()=>({create:jest.fn()}));
import { IDS, custodyOrder, driver as actor, restaurant, admin, waitCommand } from "../lib/orderCustody.fixtures";
const ID=IDS[0];
const key="prodelivery:order-custody:v1:user:driver:driver";
const order=()=>custodyOrder();
const stored={version:1,actor_id:"user",role:"driver",resource_id:"driver",order_id:"order",order_restaurant_id:"restaurant",order_driver_id:"driver",command:waitCommand(),client_operation_id:ID,expected_order_version:3,receipt:null};
const receipt=(state="pending")=>({status:state==="pending"?202:200,headers:{"retry-after":"2"},data:{client_operation_id:ID,state,order_id:state==="pending"?null:"order",order_version:state==="pending"?null:4,error_code:null,retry_after_seconds:state==="pending"?2:null}});
const missing=()=>Object.assign(new Error("404"),{response:{status:404,data:{detail:{code:"OPERATION_NOT_FOUND"}}}});
const deferred=()=>{let resolve;const promise=new Promise(yes=>{resolve=yes;});return {promise,resolve};};
let root,container,view,transport,callback;
const Probe=({user=actor,token="qa-token",online=true,item=order(),override})=>{
  view=useOrderCustodyRecovery(user,"https://qa.invalid",online,token);
  return <><CustodyRecoveryPanel recovery={{...view,...override}} isOnline={online} onAcknowledged={callback}/><CustodyControls order={item} actor={user} recovery={view} isOnline={online} incidentId={IDS[1]}/><OrderCustodySummary order={item}/></>;
};
const render=(props={},strict=false)=>act(async()=>root.render(strict?<StrictMode><Probe {...props}/></StrictMode>:<Probe {...props}/>));
const flush=()=>act(async()=>{await Promise.resolve();await Promise.resolve();await Promise.resolve();});
const event=(name,persisted=true)=>act(async()=>{const e=new Event(name);Object.defineProperty(e,"persisted",{value:persisted});window.dispatchEvent(e);});
const button=text=>[...container.querySelectorAll("button")].find(node=>node.textContent===text);
beforeEach(()=>{
  globalThis.IS_REACT_ACT_ENVIRONMENT=true;jest.clearAllMocks();window.localStorage.clear();
  Object.defineProperty(navigator,"locks",{configurable:true,value:{request:jest.fn(async(_k,_o,cb)=>cb({}))}});
  Object.defineProperty(window,"crypto",{configurable:true,value:{randomUUID:()=>ID}});
  transport={get:jest.fn(async path=>path.endsWith("auth/me")?{status:200,data:actor}:path.endsWith("capabilities")?{status:200,data:{custody_recovery_enabled:true}}:path.endsWith("/order")?{status:200,data:custodyOrder("waiting",{order_version:4})}:receipt()),post:jest.fn(async()=>receipt("applied"))};
  axios.create.mockReturnValue(transport);callback=jest.fn();container=document.createElement("div");document.body.append(container);root=createRoot(container);
});
afterEach(async()=>{await act(async()=>root.unmount());container.remove();});
test("capability default off hides mutation control and no event is sent",async()=>{
  transport.get.mockResolvedValue({status:200,data:{custody_recovery_enabled:false}});await render();await flush();expect(button("Sunt la adresă — încep așteptarea")).toBeUndefined();expect(transport.post).not.toHaveBeenCalled();
});
test("enabled own driver sees declared arrival but foreign driver does not",async()=>{
  await render();await flush();expect(button("Sunt la adresă — încep așteptarea")).toBeDefined();expect(container.textContent).toContain("Ora este consemnată de server");
  await render({item:custodyOrder(null,{driver_id:"foreign"})});expect(button("Sunt la adresă — încep așteptarea")).toBeUndefined();
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
  await act(async()=>{first=view.submit({order:order(),command:waitCommand()});second=view.submit({order:order(),command:waitCommand()});});expect(await second).toBeNull();expect(transport.post).toHaveBeenCalledTimes(1);
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
  await render();await flush();const gate=deferred();transport.post.mockReturnValue(gate.promise);let flight;await act(async()=>{flight=view.submit({order:order(),command:waitCommand()});});await event("pagehide",false);
  await act(async()=>{gate.resolve(receipt("applied"));await flight;});expect(JSON.parse(window.localStorage.getItem(key)).receipt).toBeNull();expect(view.sessionSuspended).toBe(true);
});
test("late acknowledge callback after actor switch cannot update new account",async()=>{
  const gate=deferred();window.localStorage.setItem(key,JSON.stringify({...stored,receipt:receipt("applied").data}));await render({override:{acknowledge:()=>gate.promise}});
  await act(async()=>button("Am văzut rezultatul și reîncarc comanda").click());await render({user:{...actor,id:"other",driver_id:"other-driver"}});
  await act(async()=>gate.resolve(custodyOrder("waiting",{order_version:4})));expect(callback).not.toHaveBeenCalled();
});
test("restaurant decision is distinct from actual receipt and pending blocks contradictory decisions",async()=>{
  await render({user:restaurant,item:custodyOrder("reviewed")});await flush();expect(button("Solicit returul integral")).toBeDefined();expect(button("Confirm primirea efectivă a produselor")).toBeUndefined();
  transport.post.mockResolvedValue(receipt());await act(async()=>button("Solicit returul integral").click());expect(transport.post.mock.calls[0][1]).toMatchObject({event_type:"products_disposition_decided",decision:"return",predecessor_id:IDS[3]});expect(button("Permit păstrarea de către livrator").disabled).toBe(true);
});
test("return physical receipt requires restaurant affirmation, own driver keep uses distinct action",async()=>{
  await render({user:restaurant,item:custodyOrder("return_requested")});await flush();expect(button("Confirm primirea efectivă a produselor").disabled).toBe(true);
  await act(async()=>container.querySelector('[data-testid="custody-resolution-confirm"]').click());expect(button("Confirm primirea efectivă a produselor").disabled).toBe(false);
  await render({user:actor,item:custodyOrder("keep_authorized")});await flush();expect(button("Confirm primirea efectivă a produselor")).toBeUndefined();expect(button("Confirm instrucțiunea de păstrare").disabled).toBe(true);
});
test("admin requires all contact/coordination facts but local clock cannot decide server eligibility",async()=>{
  const future=custodyOrder("waiting");future.custody_activity.wait_started_at="2099-10-14T08:01:00Z";future.custody_activity.wait_eligible_at="2099-10-14T08:11:00Z";
  await render({user:admin,item:future});await flush();expect(button("Consemnez verificarea și coordonarea").disabled).toBe(true);
  for(const name of ["customer_contact_attempted","restaurant_contacted","coordination_confirmed"]) await act(async()=>container.querySelector(`[data-testid="custody-${name}"]`).click());
  expect(button("Consemnez verificarea și coordonarea").disabled).toBe(false);await act(async()=>button("Consemnez verificarea și coordonarea").click());expect(transport.post.mock.calls[0][1]).toMatchObject({event_type:"delivery_failure_reviewed",customer_contact_attempted:true,restaurant_contacted:true,coordination_confirmed:true});expect(transport.post.mock.calls[0][1]).not.toHaveProperty("elapsed_seconds");
});
test("historical delivered custody has closed label, no active timer or custody controls",async()=>{
  await render({item:custodyOrder("reviewed",{status:"DELIVERED",delivered_at:"2026-10-14T08:21:00Z"})});expect(container.textContent).toContain("Incident închis prin livrare");expect(container.textContent).not.toContain("Estimare locală");expect(container.querySelector('[data-testid="custody-controls"]')).toBeNull();
});

const terminalReload=(capability)=>{
  const fresh=custodyOrder("waiting",{order_version:4});
  window.localStorage.setItem(key,JSON.stringify({...stored,receipt:receipt("applied").data}));
  transport.get.mockImplementation((path,config)=>path.endsWith("capabilities")?capability(config):Promise.resolve(path.endsWith("/order")?{status:200,data:fresh}:receipt("replayed")));
  return fresh;
};
const capabilityResponse=enabled=>({status:200,data:{custody_recovery_enabled:enabled}});
const checkCapability=()=>container.querySelector('[data-testid="custody-check-capability"]');

test("terminal receipt reload then acknowledge returns fresh order before read-only capability enables controls",async()=>{
  const gate=deferred(),capability=jest.fn(()=>gate.promise),fresh=terminalReload(capability);
  await render();expect(transport.get).not.toHaveBeenCalled();
  await act(async()=>button("Am văzut rezultatul și reîncarc comanda").click());
  expect(callback).toHaveBeenCalledTimes(1);expect(callback).toHaveBeenCalledWith(fresh);
  expect(window.localStorage.getItem(key)).toBeNull();expect(view.record).toBeNull();
  expect(capability).toHaveBeenCalledTimes(1);expect(view.busy).toBe(true);expect(checkCapability().disabled).toBe(true);
  await act(async()=>gate.resolve(capabilityResponse(true)));
  expect(view.capability).toEqual({ready:true,enabled:true});expect(view.busy).toBe(false);
  expect(button("Sunt la adresă — încep așteptarea").disabled).toBe(false);
  expect(transport.get.mock.calls.map(([path])=>new URL(path).pathname)).toEqual([`/api/orders/operations/custody/order/${ID}`,"/api/orders/order","/api/orders/operations/custody/capabilities"]);
  expect(transport.post).not.toHaveBeenCalled();
});

test("terminal receipt acknowledgement with disabled marker preserves fresh result and exposes manual availability check",async()=>{
  const capability=jest.fn().mockResolvedValueOnce(capabilityResponse(false)).mockResolvedValue(capabilityResponse(true));
  const fresh=terminalReload(capability);await render();
  let result;await act(async()=>{result=await view.acknowledge();});await flush();
  expect(result).toEqual(fresh);expect(view.record).toBeNull();expect(view.capability).toEqual({ready:true,enabled:false});
  expect(checkCapability().disabled).toBe(false);expect(button("Sunt la adresă — încep așteptarea")).toBeUndefined();
  await act(async()=>checkCapability().click());
  expect(view.capability.enabled).toBe(true);expect(capability).toHaveBeenCalledTimes(2);expect(transport.post).not.toHaveBeenCalled();
});

test("capability failure after acknowledgement keeps fresh callback and visible manual retry without resending",async()=>{
  const capability=jest.fn().mockRejectedValueOnce(new Error("Temporar indisponibil")).mockResolvedValue(capabilityResponse(true));
  const fresh=terminalReload(capability);await render();
  await act(async()=>button("Am văzut rezultatul și reîncarc comanda").click());await flush();
  expect(callback).toHaveBeenCalledTimes(1);expect(callback).toHaveBeenCalledWith(fresh);
  expect(view.record).toBeNull();expect(window.localStorage.getItem(key)).toBeNull();
  expect(view.capability).toEqual({ready:false,enabled:false});expect(checkCapability().disabled).toBe(false);
  expect(container.textContent).toContain("Temporar indisponibil");
  await act(async()=>checkCapability().click());expect(view.capability.enabled).toBe(true);expect(view.error).toBe("");
  expect(callback).toHaveBeenCalledTimes(1);expect(transport.post).not.toHaveBeenCalled();
});

test("late capability after terminal acknowledgement cannot enable a different actor",async()=>{
  const gate=deferred(),capability=jest.fn().mockReturnValueOnce(gate.promise).mockResolvedValue(capabilityResponse(false));
  const fresh=terminalReload(capability);await render();
  let result;await act(async()=>{result=await view.acknowledge();});expect(result).toEqual(fresh);
  const retiredSignal=capability.mock.calls[0][0].signal;
  await render({user:{...actor,id:"other",driver_id:"other-driver"},item:custodyOrder(null,{driver_id:"other-driver"})});await flush();
  expect(retiredSignal.aborted).toBe(true);expect(view.capability).toEqual({ready:true,enabled:false});
  await act(async()=>gate.resolve(capabilityResponse(true)));
  expect(view.capability).toEqual({ready:true,enabled:false});expect(view.record).toBeNull();expect(transport.post).not.toHaveBeenCalled();
});

test("unmount after terminal acknowledgement aborts capability and fences its late state update",async()=>{
  const gate=deferred(),capability=jest.fn(()=>gate.promise);terminalReload(capability);await render();
  await act(async()=>button("Am văzut rezultatul și reîncarc comanda").click());expect(callback).toHaveBeenCalledTimes(1);
  const retiredSignal=capability.mock.calls[0][0].signal;
  await act(async()=>root.render(null));expect(retiredSignal.aborted).toBe(true);
  await act(async()=>gate.resolve(capabilityResponse(true)));expect(container.textContent).toBe("");
  expect(view.capability).toEqual({ready:false,enabled:false});expect(callback).toHaveBeenCalledTimes(1);expect(transport.post).not.toHaveBeenCalled();
});

test("pagehide fences late capability after receipt clear in the same actor epoch",async()=>{
  const gate=deferred(),capability=jest.fn(()=>gate.promise);terminalReload(capability);await render();
  await act(async()=>view.acknowledge());await event("pagehide");
  expect(capability.mock.calls[0][0].signal.aborted).toBe(true);
  await act(async()=>gate.resolve(capabilityResponse(true)));
  expect(view.sessionSuspended).toBe(true);expect(view.capability).toEqual({ready:false,enabled:false});expect(transport.post).not.toHaveBeenCalled();
});

test.each([true,false])("another tab clearing terminal receipt performs only a guarded capability GET, enabled=%s",async enabled=>{
  const capability=jest.fn().mockResolvedValue(capabilityResponse(enabled));terminalReload(capability);await render();
  expect(transport.get).not.toHaveBeenCalled();const oldValue=window.localStorage.getItem(key);
  await act(async()=>{window.localStorage.removeItem(key);window.dispatchEvent(new StorageEvent("storage",{key,oldValue,newValue:null,storageArea:window.localStorage}));});await flush();
  expect(view.record).toBeNull();expect(view.capability).toEqual({ready:true,enabled});
  expect(transport.get.mock.calls.map(([path])=>new URL(path).pathname)).toEqual(["/api/orders/operations/custody/capabilities"]);
  if(!enabled)expect(checkCapability().disabled).toBe(false);
  await act(async()=>window.dispatchEvent(new StorageEvent("storage",{key:"unrelated",oldValue:null,newValue:"value"})));
  expect(capability).toHaveBeenCalledTimes(1);expect(callback).not.toHaveBeenCalled();expect(transport.post).not.toHaveBeenCalled();
});

test("external receipt clear after BFCache restoration uses the restored epoch for capability",async()=>{
  const capability=jest.fn().mockResolvedValue(capabilityResponse(true));terminalReload(capability);
  const originalGet=transport.get.getMockImplementation();
  transport.get.mockImplementation((path,config)=>path.endsWith("auth/me")?Promise.resolve({status:200,data:actor}):originalGet(path,config));
  await render();await event("pagehide");await event("pageshow");expect(view.sessionSuspended).toBe(false);
  expect(view.record.receipt.state).toBe("applied");expect(capability).not.toHaveBeenCalled();
  await act(async()=>{window.localStorage.removeItem(key);window.dispatchEvent(new StorageEvent("storage",{key,newValue:null}));});await flush();
  expect(view.record).toBeNull();expect(view.capability).toEqual({ready:true,enabled:true});
  expect(capability).toHaveBeenCalledTimes(1);expect(transport.post).not.toHaveBeenCalled();
});

test("acknowledgement retires previously enabled capability when the new availability read fails",async()=>{
  await render();await flush();expect(view.capability.enabled).toBe(true);
  await act(async()=>view.submit({order:order(),command:waitCommand()}));expect(view.record.receipt.state).toBe("applied");
  const fresh=custodyOrder("waiting",{order_version:4});
  transport.get.mockImplementation(async path=>{
    if(path.endsWith("capabilities"))throw new Error("Disponibilitate necunoscută");
    return path.endsWith("/order")?{status:200,data:fresh}:receipt("replayed");
  });
  let result;await act(async()=>{result=await view.acknowledge();});await flush();
  expect(result).toEqual(fresh);expect(view.record).toBeNull();expect(view.capability).toEqual({ready:false,enabled:false});
  expect(button("Sunt la adresă — încep așteptarea")).toBeUndefined();expect(checkCapability().disabled).toBe(false);
  expect(transport.post).toHaveBeenCalledTimes(1);
});
