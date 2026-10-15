import { createOrderStatusRecovery, validateStatusReceipt, statusFailureMessage, canChangeOrderStatus } from "./orderStatusRecovery";
const ID="f29deeb5-e7a7-4b3e-9f13-f2408365858a", actor={id:"user",role:"driver",driver_id:"driver"};
const order={id:"order",restaurant_id:"restaurant",driver_id:"driver",order_version:3,status:"ACCEPTED",preparation_status:"READY"};
const financialCodes=["FINANCIAL_SNAPSHOT_INVALID","FINANCIAL_AMOUNT_INVALID","FINANCIAL_DRIVER_TOTAL_INVALID","FINANCIAL_ACTIVITY_INVALID","FINANCIAL_PICKUP_APPROVAL_REQUIRED"];
const storage=()=>{const values=new Map();return {getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)};};
test.each(financialCodes)("financial status race %s is terminal, recoverable and acknowledgeable",async code=>{
  const rejected={status:409,data:{client_operation_id:ID,state:"rejected",order_id:null,order_version:null,error_code:code,retry_after_seconds:null}};
  const durable=storage(), api={get:jest.fn(async path=>path.endsWith("capabilities")?{status:200,data:{status_recovery_enabled:true}}:rejected),post:jest.fn(async()=>{throw Object.assign(new Error("race"),{response:rejected});})};
  const options={actor,api,durableStorage:durable,draftStorage:storage(),locks:{request:async(_key,_opts,cb)=>cb({})},crypto:{randomUUID:()=>ID},wait:async()=>{}};
  let recovery=createOrderStatusRecovery(options);expect((await recovery.submit({order,status:"PICKED_UP"})).error_code).toBe(code);expect(statusFailureMessage(code)).not.toContain("Operatia a fost respinsa");
  recovery=createOrderStatusRecovery(options);expect((await recovery.recover()).state).toBe("rejected");expect(api.post).toHaveBeenCalledTimes(1);await recovery.acknowledge();expect(recovery.snapshot()).toBeNull();
  expect(validateStatusReceipt(rejected,{client_operation_id:ID,order_id:"order",expected_order_version:3}).state).toBe("rejected");
});
test("known malformed activity disables pickup centrally; no activity preserves normal pickup",()=>{
  expect(canChangeOrderStatus(order,"PICKED_UP",actor)).toBe(true);
  for(const patch of [{financial_activity:null},{financial_activity:undefined},{read_financial_activity_invalid:true},{read_actions_unavailable:true},{financial_contract_version:1}]) expect(canChangeOrderStatus({...order,...patch},"PICKED_UP",actor)).toBe(false);
});
