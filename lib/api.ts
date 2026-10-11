import catalog from "@/backend/catalog.json";
import { serviceFor } from "./services";
import type { Business, Project, BuyerInput, Brief, Draft, Request, ProposalInput, Proposal } from "./types";

const API = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/$/, "");
export const browserRehearsal = !API;
const KEY = "dealfeed.workspace.v1";
type DB = { projects:Project[]; drafts:Draft[]; requests:Request[] };
function db(): DB { const raw = localStorage.getItem(KEY); return raw ? JSON.parse(raw) : {projects:[], drafts:[], requests:[]}; }
function save(data:DB) { localStorage.setItem(KEY, JSON.stringify(data)); }
function buyerId() { let id=localStorage.getItem("dealfeed.buyer"); if (!id) { id=`buyer-${crypto.randomUUID()}`; localStorage.setItem("dealfeed.buyer",id); } return id; }
export class ApiError extends Error { constructor(message:string, public fields:Record<string,string>={}, public code="error") { super(message); } }
let sessions:Record<string,string>={};
async function token(role:string,businessId?:string) {
  const key=role+":"+(businessId||buyerId());
  if (!sessions[key]) {
    const res=await fetch(API+"/sessions",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify({role,...(role==="buyer"?{buyerId:buyerId()}:{businessId})})});
    const body=await res.json(); if(!res.ok) throw new ApiError(body.error?.message||"Could not start a session.");
    sessions[key]=body.token;
  }
  return sessions[key];
}
async function call(path:string,body?:unknown,role="buyer",businessId?:string,retry=true):Promise<any> {
  const auth=path==="/projects"&&!body||path==="/health"?undefined:await token(role,businessId);
  const controller=new AbortController(); const timeout=setTimeout(()=>controller.abort(),85000);
  try {
    const res=await fetch(API+path,{method:body===undefined?"GET":"POST",credentials:"same-origin",headers:{"Content-Type":"application/json",...(auth?{"X-DealFeed-Authorization":`Bearer ${auth}`}:{})},...(body===undefined?{}:{body:JSON.stringify(body)}),signal:controller.signal});
    let result;
    try { result=await res.json(); } catch { throw new ApiError("The service returned an unreadable response. Your details are saved; please retry.",{},"invalid_response"); }
    if(res.status===401&&retry) {sessions={};return call(path,body,role,businessId,false);}
    if(!res.ok) throw new ApiError(result.error?.message||"The request could not be completed.",result.error?.fields,result.error?.code);
    return result;
  } catch(error) {
    if(error instanceof ApiError) throw error;
    if(process.env.NODE_ENV!=="production") console.error("DealFeed transport failure",{path,name:error instanceof Error?error.name:"UnknownError",message:error instanceof Error?error.message:"Request failed"});
    if(error instanceof Error&&error.name==="AbortError") throw new ApiError("The analysis took longer than expected. Your details are still here. Please try again.",{},"request_timeout");
    throw new ApiError("We couldn’t reach the service. Your details are still here. Please try again.",{},"network_error");
  }
  finally {clearTimeout(timeout);}
}
export function validateInput(input:BuyerInput) {
  const fields:Record<string,string>={};
  if(input.name.trim().length<2) fields.name="Enter your business name.";
  if(!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(input.email)) fields.email="Enter a valid email address.";
  if(!input.budget) fields.budget="Choose a budget, or select ‘Not sure yet’.";
  if(input.location.trim().length<2) fields.location="Tell us where your business is based.";
  const today=new Date(); today.setHours(0,0,0,0);
  if(!input.deadline||new Date(input.deadline+"T23:59:59")<today) fields.deadline="Choose today or a future deadline.";
  if(input.requirements.trim().length<20) fields.requirements="Add a little more detail (at least 20 characters).";
  if(Object.keys(fields).length) throw new ApiError("A few details need your attention.",fields,"clarification_required");
}
export async function getCatalog():Promise<{projects:Project[];businesses:Business[]}> { return API?call("/projects"):{projects:[...db().projects,...catalog.projects],businesses:catalog.businesses}; }
export async function getHealth() { return API?call("/health"):{mode:"rehearsal",storage:"browser",akamaiConfigured:false}; }
export async function generateBrief(input:BuyerInput):Promise<Draft> {
  validateInput(input);
  if(API) {
    const result=await call("/briefs",input);
    if(!result.jobId)return result;
    for(let attempt=0;attempt<60;attempt++){
      await new Promise(resolve=>setTimeout(resolve,2000));
      const status=await call(`/briefs/${result.jobId}`);
      if(status.status==="complete")return status.draft;
    }
    throw new ApiError("The brief is taking longer than expected. Your details are preserved. Please try again.");
  }
  const {projects,businesses}=await getCatalog(); const project=projects.find(p=>p.id===input.projectId); if(!project) throw new ApiError("Selected project not found.");
  const business=businesses.find(b=>b.id===project.businessId)!;
  await new Promise(resolve=>setTimeout(resolve,700));
  const service=serviceFor(project.category);
  const brief:Brief={title:`${service.category} for ${input.name}`.slice(0,180),summary:`Plan ${service.category.toLowerCase()} inspired by ${project.client} by ${business.name}. Buyer requirements: ${input.requirements}`,deliverables:service.deliverables,questions:[],constraints:[`Buyer budget target: ${input.budget} (not a quote)`,`Requested deadline: ${input.deadline} (subject to provider confirmation)`,`Location: ${input.location}`,"Availability and final pricing must be confirmed by the provider."],reference:project.title};
  const draft:Draft={id:crypto.randomUUID(),projectId:project.id,businessId:business.id,buyerId:buyerId(),input,brief,mode:"rehearsal",createdAt:new Date().toISOString(),trace:[{tool:"get_project",status:"complete",detail:project.title},{tool:"get_business",status:"complete",detail:business.name},{tool:"sample_template",status:"complete",detail:"Rehearsal template — no AI inference used"}]};
  const state=db();state.drafts.push(draft);save(state);return draft;
}
export async function approveBrief(draft:Draft,brief:Brief):Promise<Request> {
  brief={...brief,deliverables:brief.deliverables.map(s=>s.trim()).filter(Boolean)};
  if(brief.questions.length) throw new ApiError("Resolve the open questions before submitting.");
  if(brief.summary.trim().length<20||brief.title.trim().length<3||!brief.deliverables.length) throw new ApiError("Add a title, a summary, and at least one deliverable.");
  if(API)return call("/requests",{draftId:draft.id,brief,approved:true});
  const state=db();const original=state.drafts.find(d=>d.id===draft.id&&d.buyerId===buyerId());if(!original)throw new ApiError("Draft not found.");
  const existing=state.requests.find(r=>r.id===draft.id);if(existing)return existing;
  const record:Request={...original,brief:{...brief,reference:original.brief.reference},status:"submitted",approvedAt:new Date().toISOString(),trace:[...original.trace,{tool:"save_request",status:"complete",detail:"Saved after your approval"}]};state.requests.unshift(record);save(state);return record;
}
export async function getRequests(role="buyer",businessId?:string):Promise<Request[]> {return API?(await call("/requests",undefined,role,businessId)).requests:db().requests.filter(r=>role==="buyer"?r.buyerId===buyerId():r.businessId===businessId);}
export async function submitProposal(id:string,data:ProposalInput,businessId:string):Promise<Proposal> {
  if(!Number.isFinite(data.price)||data.price<0.01||data.price>1000000||data.scope.trim().length<20||data.timeline.trim().length<3)throw new ApiError("Enter a valid price, scope (20+ characters), and timeline.");
  if(API)return call(`/requests/${id}/proposal`,data,"provider",businessId);
  const state=db();const record=state.requests.find(r=>r.id===id&&r.businessId===businessId);if(!record)throw new ApiError("Request not found.");if(record.proposal)throw new ApiError("This request already has a proposal.");
  const proposal:Proposal={...data,price:Math.round(data.price*100)/100,id:crypto.randomUUID(),requestId:record.id,businessId:record.businessId,buyerId:record.buyerId,createdAt:new Date().toISOString()};record.proposal=proposal;record.status="proposed";save(state);return proposal;
}
export async function postProject(input:Pick<Project,"title"|"client"|"description"|"category"|"result"|"image">,businessId:string):Promise<Project> {
  if(API)return call("/projects",input,"provider",businessId);
  const project:Project={...input,id:crypto.randomUUID(),businessId,services:[input.category],resultNote:"Provider-supplied result for this sample business.",color:"#ece9df",featured:false,createdAt:new Date().toISOString()};const state=db();state.projects.unshift(project);save(state);return project;
}
export async function uploadImage(file:File,businessId:string):Promise<string> {
  if(!["image/png","image/jpeg","image/webp"].includes(file.type)||file.size>2000000)throw new ApiError("Choose a PNG, JPG, or WebP image under 2 MB.");
  if(API) {const health=await getHealth();if(health.storage==="dynamodb") {const upload=await call("/uploads",{contentType:file.type},"provider",businessId);const res=await fetch(upload.url,{method:"PUT",headers:{"Content-Type":file.type},body:file});if(!res.ok)throw new ApiError("Image upload failed. Please retry.");return upload.key;}}
  return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result));reader.onerror=()=>reject(new ApiError("Could not read this image."));reader.readAsDataURL(file);});
}

export async function connectedCall(path:string,body?:unknown):Promise<any> {
  if(!API)throw new ApiError("Business matching requires the connected demo API. Your inspiration is saved; the single-provider rehearsal remains available.");
  return call(path,body);
}
