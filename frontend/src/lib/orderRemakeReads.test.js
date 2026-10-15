import {parseOrderDetail, parseOrderPage} from './orderReads';
const parent={id:'parent',status:'DELIVERED',created_at:'2026-10-13T00:00:00Z',has_problem_followup:true,problem_followup_order_id:'child'};
const envelope=(order,history=[])=>({order,history,history_has_more:false,next_history_before:null,data_warnings:[]});
test('parent and child links survive page and detail reads without private operation refs',()=>{
 const p=parseOrderDetail(envelope({...parent,problem_followup_operation_ref:'private'}),'parent');
 expect(p.order.problem_followup_order_id).toBe('child');
 expect(p.order.has_problem_followup).toBe(true);
 expect(p.order).not.toHaveProperty('problem_followup_operation_ref');
 const child={id:'child',status:'NEW',created_at:parent.created_at,linked_problem_order_id:'parent',problem_type:'missing_product',problem_description:'Produs lipsă',remake_operation_ref:'private'};
 const page=parseOrderPage({items:[child],next_cursor:null,has_more:false,limit:25,data_warnings:[]});
 expect(parseOrderDetail(envelope(page.items[0]),'child').order.linked_problem_order_id).toBe('parent');
 expect(page.items[0]).not.toHaveProperty('remake_operation_ref');
 expect(page.items[0].problem_description).toBe('Produs lipsă');
});
test.each(['parent',{},true,'\nchild'])('unsafe or self link %p is unavailable',(link)=>{
 const read=parseOrderDetail(envelope({...parent,problem_followup_order_id:link}),'parent');
 expect(read.order.problem_followup_order_id).toBeNull();
 expect(read.order.read_data_invalid).toBe(true);
});
test('relationship audit preserves IDs and omits private nested data',()=>{
 const read=parseOrderDetail(envelope(parent,[{action:'order.remake_linked',created_at:parent.created_at,changes:{problem_followup_order_id:'child',linked_problem_order_id:'parent',raw:{secret:'no'}}}]),'parent');
 expect(read.history[0].changes).toEqual({problem_followup_order_id:'child',linked_problem_order_id:'parent'});
});
test('backend invalid-link flag removes navigation targets without inventing another order',()=>{
 const result=parseOrderDetail(envelope({...parent,read_remake_invalid:true}),'parent');
 expect(result.order.problem_followup_order_id).toBeNull();
 expect(result.order.read_remake_invalid).toBe(true);
 expect(result.order.read_data_invalid).toBe(true);
});
