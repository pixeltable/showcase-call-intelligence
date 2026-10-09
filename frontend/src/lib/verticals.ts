export type VerticalId = "call_center" | "sales" | "podcast" | "interview";

export const DEFAULT_VERTICAL: VerticalId = "call_center";

export interface VerticalLabels {
  uploadTitle: string;
  agentId: string;
  customerId: string;
  queue: string;
  rosterAgent: string;
  rosterCustomer: string;
  rosterQueue: string;
  qaEmpathy: string;
  qaResolution: string;
  qaCompliance: string;
  qaOverall: string;
  kpiRecordings: string;
  kpiDuration: string;
}

export interface VerticalProfile {
  id: VerticalId;
  displayName: string;
  labels: VerticalLabels;
  speakerDisplay: Record<string, string>;
}

const PROFILES: Record<VerticalId, VerticalProfile> = {
  call_center: {
    id: "call_center",
    displayName: "Call Center",
    labels: {
      uploadTitle: "Upload Call",
      agentId: "Agent ID",
      customerId: "Customer ID",
      queue: "Queue",
      rosterAgent: "Agent",
      rosterCustomer: "Customer",
      rosterQueue: "Queue",
      qaEmpathy: "Empathy",
      qaResolution: "Resolution",
      qaCompliance: "Compliance",
      qaOverall: "Overall",
      kpiRecordings: "Calls (7d)",
      kpiDuration: "Avg handle (sec)",
    },
    speakerDisplay: { AGENT: "Agent", CUSTOMER: "Customer" },
  },
  sales: {
    id: "sales",
    displayName: "Sales Call",
    labels: {
      uploadTitle: "Upload Sales Call",
      agentId: "Rep ID",
      customerId: "Prospect ID",
      queue: "Pipeline stage",
      rosterAgent: "Rep",
      rosterCustomer: "Prospect",
      rosterQueue: "Stage",
      qaEmpathy: "Rapport",
      qaResolution: "Deal progress",
      qaCompliance: "Accurate claims",
      qaOverall: "Overall",
      kpiRecordings: "Calls (7d)",
      kpiDuration: "Avg duration (sec)",
    },
    speakerDisplay: { AGENT: "Rep", CUSTOMER: "Prospect" },
  },
  podcast: {
    id: "podcast",
    displayName: "Podcast / Media",
    labels: {
      uploadTitle: "Upload Recording",
      agentId: "Host",
      customerId: "Guest / Show",
      queue: "Series",
      rosterAgent: "Host",
      rosterCustomer: "Guest",
      rosterQueue: "Series",
      qaEmpathy: "Chemistry",
      qaResolution: "Clarity",
      qaCompliance: "Factual care",
      qaOverall: "Listenability",
      kpiRecordings: "Recordings (7d)",
      kpiDuration: "Avg duration (sec)",
    },
    speakerDisplay: { AGENT: "Host", CUSTOMER: "Guest" },
  },
  interview: {
    id: "interview",
    displayName: "Interview",
    labels: {
      uploadTitle: "Upload Interview",
      agentId: "Interviewer",
      customerId: "Candidate",
      queue: "Role",
      rosterAgent: "Interviewer",
      rosterCustomer: "Candidate",
      rosterQueue: "Role",
      qaEmpathy: "Rapport",
      qaResolution: "Answer depth",
      qaCompliance: "Fair process",
      qaOverall: "Review score",
      kpiRecordings: "Interviews (7d)",
      kpiDuration: "Avg duration (sec)",
    },
    speakerDisplay: { AGENT: "Interviewer", CUSTOMER: "Candidate" },
  },
};

export const VERTICAL_OPTIONS = (Object.keys(PROFILES) as VerticalId[]).map((id) => ({
  id,
  displayName: PROFILES[id].displayName,
}));

export function normalizeVertical(vertical: string | null | undefined): VerticalId {
  if (vertical && vertical in PROFILES) {
    return vertical as VerticalId;
  }
  return DEFAULT_VERTICAL;
}

export function getProfile(vertical: string | null | undefined): VerticalProfile {
  return PROFILES[normalizeVertical(vertical)];
}

export function speakerLabel(vertical: string | null | undefined, speaker: string): string {
  const profile = getProfile(vertical);
  return profile.speakerDisplay[speaker] ?? speaker;
}

export function qaLabel(vertical: string | null | undefined, key: "empathy" | "resolution" | "compliance" | "overall"): string {
  const labels = getProfile(vertical).labels;
  if (key === "empathy") return labels.qaEmpathy;
  if (key === "resolution") return labels.qaResolution;
  if (key === "compliance") return labels.qaCompliance;
  return labels.qaOverall;
}
