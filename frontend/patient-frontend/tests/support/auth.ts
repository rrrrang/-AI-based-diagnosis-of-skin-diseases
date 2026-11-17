import { expect, type Page } from "@playwright/test";

// Current contract: a patient receives a case token; a doctor uses a demo token.
// These are test credentials, not implemented patient/doctor login sessions.
// When the backend API arrives, add agreed name/phone patient reservation lookup
// (without SMS proof) separately from doctor ID/password login. API paths,
// response fields, logout, and five-failure lock details still need the contract.
// Do not guess those details or fall back to demo auth after a login failure.
export interface WorkflowIdentity {
  requestOptions(): { headers?: Record<string, string> };
}

export interface DoctorWorkflowIdentity extends WorkflowIdentity {
  connect(page: Page, doctorUrl: string): Promise<void>;
}

function requireToken(value: unknown): string {
  // Keep credentials out of error messages and reject header whitespace/control characters.
  if (typeof value !== "string" || /\s/.test(value) || !/^[A-Za-z0-9._~+/-]+=*$/.test(value)) {
    throw new Error("A nonempty current-contract test token is required.");
  }
  return value;
}

class DemoBearerIdentity implements WorkflowIdentity {
  #token: string;

  protected constructor(token: unknown) {
    this.#token = requireToken(token);
  }

  requestOptions(): { headers: Record<string, string> } {
    return { headers: { Authorization: `Bearer ${this.#token}` } };
  }

  protected async fillDoctorToken(page: Page): Promise<void> {
    await page.getByLabel("시연용 의사 토큰").fill(this.#token);
  }
}

export class PatientCaseIdentity extends DemoBearerIdentity {
  readonly role = "patient";

  constructor(readonly caseId: string, token: unknown) {
    super(token);
    if (typeof caseId !== "string" || !caseId.trim()) {
      throw new Error("The intake response must contain a nonempty case ID.");
    }
  }
}

export class DemoDoctorIdentity extends DemoBearerIdentity implements DoctorWorkflowIdentity {
  readonly role = "doctor";

  constructor(token: unknown) {
    super(token);
  }

  async connect(page: Page, doctorUrl: string): Promise<void> {
    await page.goto(`${doctorUrl}/#/doctor`);
    await this.fillDoctorToken(page);
    const response = page.waitForResponse((r) =>
      new URL(r.url()).pathname === "/api/cases" && r.request().method() === "GET");
    await page.getByRole("button", { name: "접수 목록 연결", exact: true }).click();
    expect((await response).status(), "The actual backend must accept the doctor identity.").toBe(200);
  }
}

export function doctorIdentityFromEnvironment(
  env: NodeJS.ProcessEnv = process.env,
): DemoDoctorIdentity {
  if (!env.SKINAI_E2E_DOCTOR_TOKEN) {
    throw new Error("Missing required isolated-test setting: SKINAI_E2E_DOCTOR_TOKEN");
  }
  return new DemoDoctorIdentity(env.SKINAI_E2E_DOCTOR_TOKEN);
}

export function patientIdentityFromIntake(value: unknown): PatientCaseIdentity {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("The intake response must be an object with a case ID and access token.");
  }
  const created = value as Record<string, unknown>;
  if (typeof created.id !== "string") {
    throw new Error("The intake response must contain a case ID string.");
  }
  return new PatientCaseIdentity(created.id, created.accessToken);
}
