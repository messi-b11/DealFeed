import type { Criteria } from "./marketplace";
import type { Business, Project, ProposalInput } from "./types";

export const campaignDemoProjectId = "governor-campaign";

export function campaignDemoCriteria(projectId = campaignDemoProjectId): Criteria {
  return {
    inspirationProjectIds: [projectId],
    serviceCategory: "Speechwriting",
    description: "We are hiring a speechwriter for a fictional legislative election campaign. We need a researched ten-minute speech, a short event introduction, two rounds of revisions, and a rehearsal session. Relevant completed election campaign speechwriting is our strongest preference. Please compare that experience with municipal office announcements and keynote speaking, and distinguish proven work from skills that still need confirmation.",
    budgetCents: 600000,
    currency: "USD",
    deliverables: [
      { id: "speech", label: "Speechwriting for a ten-minute speech", mandatory: true },
      { id: "research", label: "Speech research and source notes", mandatory: true },
      { id: "intro", label: "Short event introduction", mandatory: true },
      { id: "revisions", label: "Two rounds of speech revisions", mandatory: true },
      { id: "rehearsal", label: "Speaker coaching and rehearsal support", mandatory: true },
    ],
    keywords: ["campaign speechwriting", "election campaign experience"],
    mustHaves: [],
    desiredStandard: "Clear, carefully researched writing in the speaker’s own voice. Give the greatest weight to comparable completed election campaign work.",
    location: "",
    deliveryMode: "remote",
    targetDate: null,
    buyerName: "Jordan · Sample campaign team",
  };
}

export function campaignSampleResponse(business: Business, projects: Project[], criteria?: Criteria): ProposalInput | null {
  if (criteria?.serviceCategory !== "Speechwriting") return null;
  const samples: Record<string, {price:number;timeline:string;projectId:string;fit:string;approach:string}> = {
    "campaign-voice": {
      price: 4800,
      timeline: "Three weeks after approval of the brief and source material, including two review rounds and one remote rehearsal.",
      projectId: "governor-campaign",
      fit: "Our completed speechwriting work for a fictional winning 2025 gubernatorial campaign is directly relevant to an election campaign brief. Adrian Cole has worked with campaign approval teams, changing event schedules, and candidate rehearsal. The prior election result is background context, not a guarantee of any future result.",
      approach: "Interview the speaker, review the approved brief and supplied research, prepare a sourced outline, draft the speech and introduction, complete two review rounds, and run a remote rehearsal. The client approves all facts and final text.",
    },
    "civic-script": {
      price: 3400,
      timeline: "Two weeks after approval of the brief and source material, including two review rounds and one remote rehearsal.",
      projectId: "mayor-announcements",
      fit: "Elena Brooks writes clear, concise official announcements for a fictional mayor’s office. That completed work supports careful research, public-service writing, and fast revisions. Our portfolio does not establish election campaign experience, so that transfer would need discussion with the client.",
      approach: "Confirm the speaker’s voice and approved source material, agree an outline, draft a ten-minute speech and short introduction, and incorporate two rounds of client review. Close with a remote rehearsal and a final source check.",
    },
    "maya-bennett": {
      price: 3900,
      timeline: "Three weeks after approval of the brief and source material, including two review rounds and one remote rehearsal.",
      projectId: "lead-together",
      fit: "Maya’s completed keynote work demonstrates speech structure, live delivery, and rehearsal coaching. Those skills can help a speaker sound natural. The current portfolio does not establish election campaign speechwriting, which remains a material experience gap for this brief.",
      approach: "Run a voice and delivery interview, review the client’s approved material, prepare a speech outline and draft, and refine it through two review rounds. Provide a short event introduction, source notes, and a remote rehearsal focused on delivery.",
    },
  };
  const sample = samples[business.id];
  if (!sample) return null;
  const projectIds = projects.some(project => project.id === sample.projectId && project.businessId === business.id) ? [sample.projectId] : [];
  const sampleDeliverables = new Set(campaignDemoCriteria().deliverables.map(deliverable => deliverable.label.toLowerCase()));
  return {
    price: sample.price,
    currency: "USD",
    scope: "Fictional fixed-price demo proposal: one researched ten-minute speech, one short event introduction, source notes, two consolidated rounds of revisions, and one 60-minute remote rehearsal. The stated sample total includes all demo fees; there are no recurring charges. Additional speeches or review rounds require a separate quote.",
    timeline: sample.timeline,
    fitStatement: sample.fit,
    approach: sample.approach,
    coverage: criteria.deliverables.map(deliverable => sampleDeliverables.has(deliverable.label.toLowerCase())
      ? { deliverableId: deliverable.id, status: "included", detail: "Included in the fixed sample scope, subject to the approved brief and timely client feedback." }
      : { deliverableId: deliverable.id, status: "not_stated", detail: "This edited requirement is outside the prepared demo scope. Review and state coverage before sending." }),
    exclusions: ["Additional speeches or review rounds", "On-site event attendance", "Any guarantee of an election result"],
    assumptions: ["Client supplies approved facts, source material, and one decision-maker", "Feedback is consolidated within two working days"],
    clarifications: ["Please confirm the event date, speaker availability, and approval process."],
    comparableProjectIds: projectIds,
    achievementIds: [],
  };
}
