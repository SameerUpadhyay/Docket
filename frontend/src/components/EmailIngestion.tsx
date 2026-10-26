'use client';
import {useEffect,useState} from 'react';
import {Mail,ShieldCheck,Copy,Download,Radio,RefreshCw} from 'lucide-react';
import {request,download,fetchApi} from '@/lib/api';
import type {Dossier} from '@/lib/types';

const prefix='/v1/email';
let mailStreamConnected=false;
function connectionStatus(connected:boolean){mailStreamConnected=connected;window.dispatchEvent(new CustomEvent('docket:mail-connection',{detail:connected}));}
type Route={id:string;address:string;enabled:boolean;confirmed_at:number};
type Settings={provider:string;fixed_receiving_address:boolean;connection:{last_checked:number;error_code:string}|null;delivery_configured:boolean;simulator_enabled:boolean;route:Route|null;filter_query:string};
type Verification={confirmation_code:string|null;confirmation_url:string|null;expires_at:number;simulation:boolean};
type Receipt={id:string;status:string;notice_id:string;created_at:number;error_code:string;simulation:number};

export function EmailUpdates({workspaceId,enabled,onNotices,notify}:{workspaceId:string;enabled:boolean;onNotices:(items:Dossier[])=>void;notify:(message:string)=>void}){
 useEffect(()=>{
  if(!enabled||!workspaceId)return;
  const controller=new AbortController();let cursor='';let stopped=false;
  async function handle(event:string,data:Record<string,unknown>){
   if(event==='ACCESS_REVOKED'){window.dispatchEvent(new Event('docket:session-ended'));controller.abort();return;}
   window.dispatchEvent(new CustomEvent('docket:mail',{detail:{event,data}}));
   if(event==='NEW_NOTICE_INGESTED'){
    const items=await request<Dossier[]>('/notices',{signal:controller.signal});if(!stopped){onNotices(items);notify(data.simulation?'A fictional email sample arrived.':data.quarantined?'An incoming email was quarantined.':'An incoming notice is ready. Confirm its facts before planning deadlines.');}
   }
  }
  async function connect(){
   while(!controller.signal.aborted){
    try{
     const response=await fetchApi(prefix+'/stream?after='+encodeURIComponent(cursor),{signal:controller.signal});
     if(response.status===401||response.status===403){window.dispatchEvent(new Event('docket:session-ended'));return;}
     if(!response.ok||!response.body)throw new Error('Mail updates unavailable');
     connectionStatus(true);
     const reader=response.body.getReader();const decoder=new TextDecoder();let buffer='';
     try{while(!controller.signal.aborted){
      const chunk=await reader.read();if(chunk.done)break;buffer+=decoder.decode(chunk.value,{stream:true});
      if(buffer.length>65536)throw new Error('Oversized mail event');
      let boundary:number;
      while((boundary=buffer.indexOf('\n\n'))>=0){
       const frame=buffer.slice(0,boundary);buffer=buffer.slice(boundary+2);let event='',id='';const data:string[]=[];
       for(const line of frame.split('\n')){if(line.startsWith('event:'))event=line.slice(6).trim();if(line.startsWith('id:'))id=line.slice(3).trim();if(line.startsWith('data:'))data.push(line.slice(5).trimStart());}
       if(event&&data.length){await handle(event,JSON.parse(data.join('\n')));if(id)cursor=id;}
      }
     }}finally{await reader.cancel().catch(()=>{});reader.releaseLock();}
    }catch(error){if((error as Error).name==='AbortError')return;}
    connectionStatus(false);
    if(!controller.signal.aborted)await new Promise<void>(resolve=>{const timer=setTimeout(resolve,2000);controller.signal.addEventListener('abort',()=>{clearTimeout(timer);resolve();},{once:true});});
   }
  }
  void connect();
  return()=>{stopped=true;controller.abort();connectionStatus(false);};
 },[workspaceId,enabled,onNotices,notify]);
 return null;
}

export function EmailSetup(){
 const [settings,setSettings]=useState<Settings|null>(null),[verification,setVerification]=useState<Verification|null>(null),[receipts,setReceipts]=useState<Receipt[]>([]);
 const [consent,setConsent]=useState(false),[confirmed,setConfirmed]=useState(false),[busy,setBusy]=useState(false),[message,setMessage]=useState(''),[connected,setConnected]=useState(mailStreamConnected);
 async function load(){
  const [options,codes,deliveries]=await Promise.all([request<Settings>(prefix+'/settings'),request<{verification:Verification|null}>(prefix+'/verification'),request<Receipt[]>(prefix+'/receipts')]);
  setSettings(options);setVerification(codes.verification);setReceipts(deliveries);
 }
 useEffect(()=>{
  let active=true;
  void load().catch(e=>{if(active)setMessage(e.message);});
  const mail=()=>{if(active)void load().catch(e=>setMessage(e.message));};
  const connection=(event:Event)=>setConnected(Boolean((event as CustomEvent).detail));
  window.addEventListener('docket:mail',mail);window.addEventListener('docket:mail-connection',connection);
  // Also expire displayed codes and refresh receipts when a stream is interrupted.
  const timer=setInterval(mail,15000);
  return()=>{active=false;clearInterval(timer);window.removeEventListener('docket:mail',mail);window.removeEventListener('docket:mail-connection',connection);};
 },[]);
 async function action(path:string,method='POST',body:unknown={consent:true}){
  setBusy(true);setMessage('');try{await request(prefix+path,{method,...(method==='DELETE'?{}:{headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});await load();setMessage(method==='DELETE'?'Receiving disabled. Remove the Gmail rule too.':path==='/routing'?(settings?.delivery_configured?'Receiving enabled. Set up forwarding below.':'Local preview enabled. Try the fictional test messages below.'):path==='/routing/rotate'?'Address replaced. Update your mailbox forwarding rule.':'Saved.');}catch(e){setMessage((e as Error).message);}finally{setBusy(false);}
 }
 const route=settings?.route;const enabled=!!route?.enabled;
 const code=verification&&verification.expires_at*1000>Date.now()?verification:null;
 return <section className="pilot-card email-setup"><div className="email-title"><Mail size={24}/><div><h2>Selective email forwarding</h2><p>Receive notices without giving Docket access to your inbox.</p></div></div>
  <div className="email-privacy"><ShieldCheck size={19}/><span>Your mailbox applies a rule you review. Only forwarded messages reach the receiving provider and this workspace. Keyword rules can also match personal mail.</span></div>
  {message&&<p role="status" className="pilot-message">{message}</p>}
  {!settings&&<p>Loading mail settings…</p>}
  {settings?.provider==='agentmail'&&settings.delivery_configured&&<p className="email-preview"><strong>Dedicated AgentMail inbox.</strong> Docket uses an inbox-scoped read-only key and checks for new forwarded mail about every 15 seconds while the app server is running. It cannot send or delete mail. Keep this computer and the app running for processing. {settings.connection?.error_code?<>Connection needs attention: {settings.connection.error_code.replaceAll('-',' ')}. Check the server credential and inbox access.</>:settings.connection?.last_checked?<>Last checked {new Date(settings.connection.last_checked*1000).toLocaleTimeString()}.</>:<>Enable receiving below to start.</>}</p>}
  {settings&&!settings.delivery_configured&&<p className="email-preview" role="note"><strong>Local preview.</strong> Internet email is not connected. This preview address cannot be added to Gmail. Configure an inbound provider and receiving address first, then replace the preview address. You can use the fictional test messages below meanwhile.</p>}
  {!enabled?<><label className="pilot-check"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/><span>I control the forwarding mailbox and have authority to share the selected notices with this workspace and its receiving provider.</span></label><button className="pilot-primary" disabled={!consent||busy||!settings} onClick={()=>action('/routing')}>Enable {settings?.delivery_configured?'receiving address':'local preview'}</button></>:<>
   <ol className="email-steps"><li><span className="email-step">1</span><div><h3>Your receiving address</h3><p>Use this Docket receiving address, not your own Gmail address. Add this destination under Gmail → Settings → Forwarding and POP/IMAP. Keep forwarding disabled for all mail; use a selective filter.</p><div className="email-address"><code>{route!.address}</code><button className="pilot-secondary" aria-label="Copy receiving address" onClick={()=>navigator.clipboard.writeText(route!.address).then(()=>setMessage('Address copied.')).catch(()=>setMessage('Select and copy the address manually.'))}><Copy size={16}/></button></div>{settings?.delivery_configured&&<a href="https://mail.google.com/mail/u/0/#settings/fwdandpop" target="_blank" rel="noreferrer">Open Gmail forwarding settings ↗</a>}</div></li>
    <li><span className="email-step">2</span><div><h3>Confirm in Gmail</h3><p className="email-listening"><Radio size={16}/>{connected?'Live updates connected':'Checking for updates'} · codes remain available for 10 minutes.</p>
     {code?<div className={'email-verification'+(code.simulation?' email-preview':'')}><strong>{code.simulation?'Fictional test confirmation':'Google forwarding confirmation received'}</strong>{code.confirmation_code&&<code aria-label="Forwarding confirmation code">{code.confirmation_code}</code>}{code.confirmation_url&&<a href={code.confirmation_url} target="_blank" rel="noreferrer">Review Google confirmation link ↗</a>}<p>Docket does not confirm forwarding automatically. Complete the step in Gmail.</p></div>:<p>Waiting for an authenticated Google confirmation message. You can also confirm through your receiving provider if verification is unavailable here.</p>}
     <label className="pilot-check"><input type="checkbox" checked={confirmed||!!route!.confirmed_at} onChange={e=>setConfirmed(e.target.checked)} disabled={!settings?.delivery_configured||!!route!.confirmed_at}/><span>I completed the forwarding confirmation in Gmail.</span></label><button className="pilot-secondary" disabled={busy||!settings?.delivery_configured||!confirmed||!!route!.confirmed_at} onClick={()=>action('/routing/confirm')}>{route!.confirmed_at?'Marked confirmed by owner':'Save confirmation'}</button></div></li>
    <li><span className="email-step">3</span><div><h3>Review and import your filter</h3><p>Gmail → Filters and blocked addresses → Import filters. Review the matched mail before enabling the rule. Sender matches and keywords do not authenticate a notice.</p><details><summary>View the exact Gmail search rule</summary><pre>{settings?.filter_query}</pre></details><button className="pilot-primary" disabled={busy||!settings?.delivery_configured||!route!.confirmed_at} onClick={()=>download(prefix+'/gmail-filter.xml','docket-selective-mail-filter.xml').catch(e=>setMessage(e.message))}><Download size={16}/> Download filter XML</button></div></li></ol>
   <details className="email-controls"><summary>Receiving controls</summary><p>For a fixed AgentMail inbox, configure a different provider inbox before replacing its address. Changing a routed address invalidates the old one. Disabling intake clears pending messages and codes; existing cases remain until deleted. Remove or update the rule in Gmail too.</p><div className="pilot-inline"><button className="pilot-secondary" disabled={busy} onClick={()=>action('/routing/rotate')}>Replace address</button><button className="pilot-danger" disabled={busy} onClick={()=>action('/routing','DELETE')}>Disable receiving</button></div></details>
  </>}
  {enabled&&settings?.simulator_enabled&&<details className="email-simulator"><summary>Local test messages · fictional data</summary><p>These use the intake pipeline in this workspace, are labelled as samples, and never verify an actual sender or mailbox.</p><div className="email-simulator-grid">{[['verification','Google confirmation'],['gst','GST notice + PDF'],['legal','Manual legal forward'],['phishing','Spoofed payment demand']].map(([scenario,label])=><button className="pilot-secondary" key={scenario} disabled={busy} onClick={()=>action('/simulate','POST',{scenario})}>{label}</button>)}</div></details>}
  {!!receipts.length&&<details className="email-receipts"><summary>Recent incoming deliveries ({receipts.length})</summary>{receipts.map(r=><div key={r.id}><span>{r.simulation?'Sample · ':''}{r.status.replaceAll('_',' ')}</span><small>{new Date(r.created_at*1000).toLocaleString()}{r.error_code?' · '+r.error_code.replaceAll('-',' '):''}</small></div>)}</details>}
  <button className="pilot-back" disabled={busy} onClick={()=>load().catch(e=>setMessage(e.message))}><RefreshCw size={14}/>Refresh mail status</button>
 </section>;
}

export function EmailDetails({dossier,role}:{dossier:Dossier;role:string}){
 const [mapping,setMapping]=useState<Record<string,string>|null>(null),[message,setMessage]=useState('');
 useEffect(()=>{setMapping(null);setMessage('');},[dossier.id]);
 if(dossier.ingestion_channel!=='EMAIL_FORWARD')return null;
 let excerpt=dossier.redacted_ocr_excerpt;
 if(mapping)for(const [token,value]of Object.entries(mapping))excerpt=excerpt.replaceAll(token,value);
 const mail=dossier.email_intake;
 return <section className="pilot-card email-case"><h2>{mail?.simulation?'Sample email':'Incoming email'}</h2><p>{mail?.subject}</p><p>Sender: {mail?.chain_forensics?.original_sender_email||'Unknown'} · {mail?.chain_forensics?.authentication_status||'Unverified'}</p><p>No deadline is scheduled until the case facts are confirmed. {dossier.pii_tokens_redacted_count} identifiers were masked locally; masking may miss personal data.</p><details><summary>Read the email extraction</summary><pre>{excerpt}</pre></details>{role!=='reviewer'&&<button className="pilot-secondary" onClick={async()=>{if(mapping){setMapping(null);return;}try{const result=await request<{mapping:Record<string,string>}>(prefix+'/notices/'+dossier.id+'/pii');setMapping(result.mapping);}catch(e){setMessage((e as Error).message);}}}>{mapping?'Hide original identifiers':'Reveal identifiers on this device · available for 24 hours'}</button>}{message&&<p role="status">{message}</p>}</section>;
}
