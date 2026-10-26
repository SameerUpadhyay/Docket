import type {Dossier} from './types';
let workspace='';
export function selectWorkspace(id:string){workspace=id;}
function headers(extra?:HeadersInit){const value=new Headers(extra);value.set('X-Docket-Request','1');if(workspace)value.set('X-Workspace-ID',workspace);return value;}
export function fetchApi(path:string,options?:RequestInit){return fetch('/api'+path,{...options,headers:headers(options?.headers),credentials:'same-origin',cache:'no-store'});}
export async function request<T>(path:string,options?:RequestInit):Promise<T>{
 const response=await fetch('/api'+path,{...options,headers:headers(options?.headers),credentials:'same-origin',cache:'no-store'});
 if(!response.ok){const body=await response.json().catch(()=>({detail:'The server could not complete this request.'}));if(response.status===401&&!path.startsWith('/auth/login')||response.status===403&&String(body.detail).startsWith('Workspace access was revoked'))window.dispatchEvent(new Event('docket:session-ended'));throw new Error(typeof body.detail==='string'?body.detail:'Check the required fields and try again.');}
 return response.json();
}
export const patch=(path:string,body:unknown)=>request<Dossier>(path,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
export async function download(path:string,name:string,method='GET'){
 const response=await fetch('/api'+path,{method,headers:headers(),credentials:'same-origin',cache:'no-store'});
 if(!response.ok) throw new Error('Download failed. Check the backend connection.');
 const url=URL.createObjectURL(await response.blob());const link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
export function currency(n:number){return new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:0}).format(n);}
export function shortDate(value:string){return new Date(value+'T12:00:00+05:30').toLocaleDateString('en-IN',{day:'2-digit',month:'short',timeZone:'Asia/Kolkata'});}
export async function requestBlob(path:string):Promise<Blob>{
 const response=await fetch('/api'+path,{headers:headers(),credentials:'same-origin',cache:'no-store'});
 if(!response.ok){const body=await response.json().catch(()=>({detail:'Source preview is unavailable.'}));throw new Error(body.detail||'Source preview is unavailable.');}
 return response.blob();
}
