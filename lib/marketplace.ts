import type { Project, Request, Trace } from "./types";
import { ApiError, connectedCall } from "./api";

export type Deliverable = { id:string; label:string; mandatory:boolean };
export type Criteria = {
  preferencesConfirmed?:boolean; inspirationProjectIds:string[]; description:string; serviceCategory:string; budgetCents:number|null; currency:string;
  deliverables:Deliverable[]; keywords:string[]; mustHaves:string[]; desiredStandard:string; location:string;
  deliveryMode:"remote"|"onsite"|"hybrid"; targetDate:string|null; buyerName:string;
};
export type Evidence = {id:string;businessId?:string;projectId?:string;kind:string;title:string;url?:string;excerpt:string;provenance:string;retrievedAt?:string;fixtureCreatedAt?:string;version?:string};
export type Assessment = {id:string;label:string;status:string;explanation:string;evidenceIds?:string[]};
export type SemanticInsight = {businessIds:string[];detail:string;quotes:{evidenceId:string;quote:string}[];evidenceIds:string[];label:string};
export type ExperienceFit = {level:"direct"|"related"|"unknown";summary:string;evidenceIds:string[];context:string};
export type Match = {experienceFit?:ExperienceFit;semanticInsights?:SemanticInsight[];businessId:string;rank:number;summary:string;comparableProjectIds:string[];criteria:Assessment[];strengths:string[];gaps:string[];questions:string[];budget?:{status:string;explanation:string;minimumCents?:number};evidence:Evidence[];achievements?:{title:string;evidenceIds:string[]}[]};
export type MatchRun = {id:string;criteria:Criteria;status:string;matches:Match[];shortfallReason?:string;mode:string;trace:Trace[];evidenceVersion?:string;createdAt:string};
export type Comparison = {mode?:string;summary?:string;recommendation?:string;businesses?:any[];proposals?:any[];findings?:any[];questions?:string[];trace?:Trace[];[key:string]:any};
export type Deal = {id:string;criteria:Criteria;approvedBrief:Criteria;briefVersion:number;status:string;businessIds:string[];requestIds:string[];requests:Request[];proposals:NonNullable<Request["proposal"]>[];createdAt:string;approvedAt:string;selectedRequestId?:string|null;selectedBusinessId?:string|null;comparison?:Comparison|null;comparisonStatus?:string};
export type PortfolioProject = Project & {styleTags?:string[];capabilities?:string[];status?:string;visibility?:string;achievements?:{id:string;claim?:string;title?:string}[]};
export const newKey=()=>crypto.randomUUID();
export const currency=(cents:number,currency="USD")=>new Intl.NumberFormat("en-US",{style:"currency",currency,maximumFractionDigits:2}).format(cents/100);
export const shortDate=(value?:string)=>value&&!Number.isNaN(new Date(value).getTime())?new Date(value).toLocaleDateString("en-US",{month:"short",day:"numeric",year:"numeric"}):"Date unavailable";
export async function getMatch(id:string):Promise<MatchRun>{
  const result=await connectedCall(`/matches/${encodeURIComponent(id)}`);
  if(result.status==="failed")throw new ApiError("Analysis could not finish. Your requirements are preserved; please retry.",{},"inference_unavailable");
  return result;
}
export async function waitForMatch(id:string):Promise<MatchRun>{
  for(let attempt=0;attempt<75;attempt++){
    const status=await getMatch(id);
    if(status.status==="complete")return status;
    if(status.status!=="pending"&&status.status!=="running")throw new ApiError("The analysis returned an unexpected status. Your requirements are preserved; please retry.",{},"invalid_response");
    await new Promise(resolve=>setTimeout(resolve,2000));
  }
  throw new Error("Analysis is still running. Your draft is saved; use Refresh analysis to recover the result.");
}
export async function createMatch(criteria:Criteria,onPending:(id:string)=>void):Promise<MatchRun>{
  const result=await connectedCall("/matches",{criteria});
  if(!result.jobId)return result;
  onPending(result.jobId);
  return waitForMatch(result.jobId);
}
export async function approveMatch(matchRunId:string,businessIds:string[],idempotencyKey:string):Promise<Deal>{return connectedCall("/deals",{matchRunId,businessIds,approved:true,idempotencyKey});}
export async function getDeals():Promise<Deal[]>{return (await connectedCall("/deals")).deals;}
export async function getDeal(id:string):Promise<Deal>{return connectedCall(`/deals/${encodeURIComponent(id)}`);}
export async function compareDeal(id:string):Promise<Comparison>{
  const result=await connectedCall(`/deals/${encodeURIComponent(id)}/compare`,{});
  if(!result.jobId)return result.comparison||result;
  for(let attempt=0;attempt<75;attempt++){await new Promise(resolve=>setTimeout(resolve,2000));const deal=await getDeal(id);if(deal.comparison)return deal.comparison;if(deal.comparisonStatus==="failed")throw new Error("The comparison could not be completed. Your responses are saved. Try again.");}
  throw new Error("Comparison is still running. Refresh this deal shortly to recover the result.");
}
export async function selectProvider(id:string,requestId:string):Promise<Deal>{return connectedCall(`/deals/${encodeURIComponent(id)}/selection`,{requestId});}
