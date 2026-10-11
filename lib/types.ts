export type BusinessProfile = {
  foundedYear:number; teamSize:string; lead:{name:string;title:string;bio:string}; overview:string;
  idealClients:string[]; specialties:string[]; process:{title:string;description:string}[]; engagements:string[];
  languages:string[]; typicalTimeline:string; pricingSummary:string; availabilityNote:string;
  experience:{title:string;organization:string;period:string;summary:string;projectIds:string[]}[]; boundaries:string[];
};
export type Business = { id:string; name:string; initials:string; location:string; tagline:string; description:string; services:string[]; email:string; website:string; color:string; sample:boolean; profile?:BusinessProfile; achievements?:{id:string;title:string;projectId:string;description?:string;provenance?:string}[] };
export type Project = { archived?:boolean; id:string; businessId:string; title:string; client:string; description:string; category:string; services:string[]; result:string; resultNote:string; image:string; imageAlt?:string; imagePosition?:string; imageCredit?:{photographer:string;sourceUrl:string;source:string}; color:string; featured:boolean; createdAt:string; caseStudy?:{challenge:string;approach:string;deliverables:string[];outcome:string} };
export type BuyerInput = { projectId:string; name:string; email:string; budget:string; location:string; deadline:string; requirements:string };
export type Brief = { title:string; summary:string; deliverables:string[]; questions:string[]; constraints:string[]; reference:string };
export type Trace = { tool:string; status:string; detail:string };
export type Draft = { id:string; projectId:string; businessId:string; buyerId:string; input:BuyerInput; brief:Brief; mode:string; trace:Trace[]; createdAt:string };
export type Proposal = { id:string; requestId:string; businessId:string; buyerId:string; price:number; currency:string; scope:string; timeline:string; createdAt:string; priceCents?:number; fitStatement?:string; approach?:string; coverage?:{deliverableId:string;status:string;detail:string}[]; exclusions?:string[]; assumptions?:string[]; clarifications?:string[]; comparableProjectIds?:string[]; achievementIds?:string[] };
export type Request = Draft & { status:"submitted"|"proposed"; approvedAt:string; proposal?:Proposal; dealId?:string; briefVersion?:number; criteria?:import("./marketplace").Criteria };
export type ProposalInput = { price:number; currency:string; scope:string; timeline:string; fitStatement?:string; approach?:string; coverage?:{deliverableId:string;status:"included"|"excluded"|"partial"|"not_stated";detail:string}[]; exclusions?:string[]; assumptions?:string[]; clarifications?:string[]; comparableProjectIds?:string[]; achievementIds?:string[] };
