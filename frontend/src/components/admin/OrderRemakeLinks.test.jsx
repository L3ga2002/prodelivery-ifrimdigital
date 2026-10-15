import {act} from 'react';
import {createRoot} from 'react-dom/client';
import axios from 'axios';
import {OrderReadBrowser} from './OrderReadBrowser';
jest.mock('axios',()=>({create:jest.fn()}));
jest.mock('../ui/dialog',()=>{
 const Part=({children,...props})=><div data-testid={props['data-testid']}>{children}</div>;
 return {Dialog:({open,children})=>open?<div>{children}</div>:null,DialogContent:Part,DialogDescription:Part,DialogHeader:Part,DialogTitle:Part,DialogFooter:Part};
});
const parent={id:'parent',order_number:'S.0100',restaurant_id:'r',status:'DELIVERED',created_at:'2026-10-13T00:00:00Z',source:'S',has_problem_followup:true,problem_followup_order_id:'child'};
const child={...parent,id:'child',order_number:'S.0101P',status:'NEW',has_problem_followup:false,problem_followup_order_id:null,linked_problem_order_id:'parent',problem_description:'Produs lipsă'};
let box,root,transport,context;
const render=()=>act(async()=>root.render(<OrderReadBrowser context={context}/>));
const clickText=(text)=>act(async()=>{
 const node=[...box.querySelectorAll('button')].find(el=>el.textContent===text);expect(node).toBeTruthy();node.click();
});
beforeEach(()=>{
 globalThis.IS_REACT_ACT_ENVIRONMENT=true;
 context={actorId:'admin',role:'admin',token:'qa-token',apiUrl:'https://qa.invalid',isOnline:true,reloadKey:0};
 transport={get:jest.fn(async(url)=>({data:url.includes('/detail/')?{order:url.endsWith('/child')?child:parent,history:[],history_has_more:false,next_history_before:null,data_warnings:[]}:{items:[parent],limit:25,next_cursor:null,has_more:false,data_warnings:[]}}))};
 axios.create.mockReturnValue(transport);box=document.createElement('div');document.body.append(box);root=createRoot(box);
});
afterEach(async()=>{await act(async()=>root.unmount());box.remove();jest.clearAllMocks();});
test('following the child and returning to parent performs fresh authenticated reads',async()=>{
 await render();await act(async()=>box.querySelector('[data-testid="order-read-eye-parent"]').click());
 await clickText('Vezi comanda suplimentară');
 expect(box.querySelector('[data-testid="order-read-detail"]').textContent).toContain('S.0101P');
 expect(box.textContent).toContain('Produs lipsă');
 await clickText('Vezi comanda inițială');
 expect(box.querySelector('[data-testid="order-read-detail"]').textContent).toContain('S.0100');
 expect(transport.get.mock.calls.filter(([url])=>url.includes('/detail/')).map(([url])=>url.split('/').at(-1))).toEqual(['parent','child','parent']);
});
test('account switch closes selected relation detail before another account reads it',async()=>{
 await render();await act(async()=>box.querySelector('[data-testid="order-read-eye-parent"]').click());
 await clickText('Vezi comanda suplimentară');
 context={...context,actorId:'other',token:'other-token'};await render();
 expect(box.querySelector('[data-testid="order-read-detail"]')).toBeNull();
});
