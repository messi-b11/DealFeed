import { ArrowUpRight, CheckCircle2, Clock3, Users } from "lucide-react";
import type { Business, Project } from "@/lib/types";

export function BusinessProfileDetails({ business, projects, onProject }: {
  business: Business;
  projects: Project[];
  onProject: (project: Project) => void;
}) {
  const profile = business.profile;
  if (!profile) return <p className="profile-overview">{business.description}</p>;
  return <div className="business-profile-details">
    <div className="profile-facts">
      <span><small>Established</small><strong>{profile.foundedYear}</strong></span>
      <span><small><Users size={13}/> Team</small><strong>{profile.teamSize}</strong></span>
      <span><small><Clock3 size={13}/> Typical engagement</small><strong>{profile.typicalTimeline}</strong></span>
      <span><small>Working languages</small><strong>{profile.languages.join(" · ")}</strong></span>
    </div>
    <section className="profile-story">
      <div><span className="eyebrow">THE PEOPLE BEHIND THE WORK</span><h2>A business with a point of view.</h2><p>{profile.overview}</p></div>
      <aside className="profile-lead"><span className="profile-lead-monogram" aria-hidden="true">{profile.lead.name.split(" ").map(n=>n[0]).slice(0,2).join("")}</span><div><h3>{profile.lead.name}</h3><small>{profile.lead.title}</small></div><p>{profile.lead.bio}</p></aside>
    </section>
    <div className="profile-detail-grid">
      <section className="profile-detail-panel"><span className="eyebrow">WHAT WE DO WELL</span><h3>Specialties &amp; client fit</h3><div className="project-tags">{profile.specialties.map(item=><span key={item}>{item}</span>)}</div><h4>We often work with</h4><ul>{profile.idealClients.map(item=><li key={item}>{item}</li>)}</ul></section>
      <section className="profile-detail-panel"><span className="eyebrow">WORKING TOGETHER</span><h3>Engagements &amp; practical details</h3><ul>{profile.engagements.map(item=><li key={item}>{item}</li>)}</ul><h4>Pricing approach</h4><p>{profile.pricingSummary}</p><p className="profile-availability"><Clock3 size={14}/>{profile.availabilityNote}</p></section>
    </div>
    <section className="profile-experience"><span className="eyebrow">RELEVANT BACKGROUND</span><h2>Experience you can explore.</h2><div className="profile-experience-list">{profile.experience.map((experience,index)=><article key={`${experience.title}-${index}`}><span className="experience-marker"><CheckCircle2 size={17}/></span><div><small>{experience.period} · {experience.organization}</small><h3>{experience.title}</h3><p>{experience.summary}</p><div className="profile-evidence-links">{experience.projectIds.map(id=>{const project=projects.find(p=>p.id===id);return project?<button className="source-button" key={id} onClick={()=>onProject(project)}>{project.title}<ArrowUpRight size={13}/></button>:null;})}</div></div></article>)}</div><small className="profile-source-note">Fictional background and sample completed work for this demo. Website corroboration is optional; the analysis can use the portfolio and business profile.</small></section>
    <section className="profile-process"><span className="eyebrow">FROM BRIEF TO DELIVERY</span><h2>How we work.</h2><ol>{profile.process.map((step,index)=><li key={step.title}><span>{String(index+1).padStart(2,"0")}</span><h3>{step.title}</h3><p>{step.description}</p></li>)}</ol></section>
    <section className="profile-boundaries"><h3>What to confirm before starting</h3><ul>{profile.boundaries.map(item=><li key={item}>{item}</li>)}</ul></section>
  </div>;
}

export function ProjectCaseStudy({ project }: { project: Project }) {
  const study = project.caseStudy;
  if (!study) return null;
  return <div className="project-case-study"><section><h3>The brief</h3><p>{study.challenge}</p></section><section><h3>The approach</h3><p>{study.approach}</p></section><section><h3>What was delivered</h3><ul>{study.deliverables.map(item=><li key={item}>{item}</li>)}</ul></section><section><h3>The outcome</h3><p>{study.outcome}</p></section></div>;
}
