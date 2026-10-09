export const COLORS=['#8b5cf6','#3b82f6','#f59e0b','#10b981','#ec4899'];
export const clone=v=>structuredClone(v);
export function imageRect(width,height,imageWidth,imageHeight){const scale=Math.min(width/imageWidth,height/imageHeight);return {x:(width-imageWidth*scale)/2,y:(height-imageHeight*scale)/2,width:imageWidth*scale,height:imageHeight*scale};}
export function toImage(x,y,r){if(x<r.x||y<r.y||x>r.x+r.width||y>r.y+r.height)return null;return {x:(x-r.x)/r.width,y:(y-r.y)/r.height};}
export function createMapping(state,source,target){const n=state.next_display_index;return {id:crypto.randomUUID(),display_index:n,color:COLORS[(n-1)%5],mode:'replace',source:clone(source),target:clone(target)};}
export function addMapping(state,mapping){return {...state,mappings:[...state.mappings,mapping],next_display_index:Math.max(state.next_display_index,mapping.display_index+1)};}
export class UndoStack{constructor(){this.past=[];this.future=[];}push(state){this.past.push(clone(state));if(this.past.length>60)this.past.shift();this.future=[];}undo(state){if(!this.past.length)return state;this.future.push(clone(state));return this.past.pop();}redo(state){if(!this.future.length)return state;this.past.push(clone(state));return this.future.pop();}}
export class LatestRequest{constructor(){this.version=0;this.controller=null;}cancel(){this.version++;this.controller?.abort();}start(){this.cancel();this.controller=new AbortController();return {version:this.version,signal:this.controller.signal};}current(version){return version===this.version;}}
