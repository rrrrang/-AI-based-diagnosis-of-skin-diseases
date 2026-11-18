import { expect, type APIRequestContext, type Page, type Response } from "@playwright/test";

// Login sessions and legacy case credentials are deliberately separate. A failed
// login never falls back to a case token or the old demo-doctor authentication.
export interface WorkflowIdentity {
  requestOptions(): { headers: Record<string, string> };
}

export interface DoctorWorkflowIdentity {
  connect(page: Page, doctorUrl: string): Promise<LoginSessionIdentity>;
}

function requireToken(value: unknown): string {
  if (typeof value !== "string" || /\s/.test(value) || !/^[A-Za-z0-9._~+/-]+=*$/.test(value)) {
    throw new Error("A nonempty valid test access token is required.");
  }
  return value;
}

class BearerIdentity implements WorkflowIdentity {
  #token: string;

  protected constructor(token: unknown) {
    this.#token = requireToken(token);
  }

  requestOptions(): { headers: Record<string, string> } {
    return { headers: { Authorization: `Bearer ${this.#token}` } };
  }
}

export class PatientCaseIdentity extends BearerIdentity {
  readonly kind = "case";

  constructor(readonly caseId: string, token: unknown) {
    super(token);
    if (typeof caseId !== "string" || !caseId.trim()) {
      throw new Error("The intake response must contain a nonempty case ID.");
    }
  }
}

export class LoginSessionIdentity extends BearerIdentity {
  readonly kind = "session";

  constructor(
    token: unknown,
    readonly role: "patient" | "doctor",
    readonly loginId: string,
    readonly doctorId: string | null,
    readonly expiresAt: number,
  ) {
    super(token);
  }

  async logout(client: APIRequestContext, apiUrl: string): Promise<void> {
    const response = await client.post(`${apiUrl}/api/auth/logout`, this.requestOptions());
    expect(response.status(), "The backend must revoke this login session.").toBe(204);
  }
}

export function sessionIdentityFromLogin(value: unknown, expectedRole: "patient" | "doctor"): LoginSessionIdentity {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Expected a successful login response.");
  }
  const body = value as Record<string, unknown>;
  if (body.role !== expectedRole || typeof body.loginId !== "string" || !body.loginId.trim() ||
      typeof body.expiresAt !== "number" || !Number.isFinite(body.expiresAt) || body.expiresAt <= 0 ||
      typeof body.name !== "string" || !body.name.trim() ||
      (expectedRole === "patient" ? body.doctorId !== null :
        typeof body.doctorId !== "string" || !body.doctorId.trim())) {
    throw new Error("The login response does not match the expected session contract.");
  }
  return new LoginSessionIdentity(body.accessToken, expectedRole, body.loginId,
    body.doctorId as string | null, body.expiresAt);
}

async function sessionFromUiResponse(response: Response, role: "patient" | "doctor") {
  expect(response.status(), `The actual backend must accept the ${role} login.`).toBe(200);
  return sessionIdentityFromLogin(await response.json(), role);
}

export async function patientLoginViaUi(page: Page, phone: string, name: string, create = true) {
  await page.goto("/#/patient/login");
  await page.getByLabel("전화번호", { exact: true }).fill(phone);
  await page.getByLabel("이름", { exact: true }).fill(name);
  const response = page.waitForResponse((r) =>
    new URL(r.url()).pathname === "/api/auth/patient" && r.request().method() === "POST");
  await page.getByRole("button", { name: create ? "시작하기" : "분석 결과 확인", exact: true }).click();
  return sessionFromUiResponse(await response, "patient");
}

export async function logoutViaUi(page: Page): Promise<void> {
  const response = page.waitForResponse((r) =>
    new URL(r.url()).pathname === "/api/auth/logout" && r.request().method() === "POST");
  await page.getByRole("button", { name: "로그아웃", exact: true }).click();
  expect((await response).status(), "UI logout must reach the actual backend.").toBe(204);
}

export class DoctorLoginIdentity implements DoctorWorkflowIdentity {
  #loginId: string;
  #password: string;

  constructor(loginId: string, password: string) {
    if (typeof loginId !== "string" || !loginId.trim() || loginId.length > 30 ||
        typeof password !== "string" || !password.trim() || password.length > 72 || /[\r\n\0]/.test(password)) {
      throw new Error("Valid isolated-test doctor login credentials are required.");
    }
    this.#loginId = loginId.trim();
    this.#password = password;
  }

  async login(client: APIRequestContext, apiUrl: string): Promise<LoginSessionIdentity> {
    const response = await client.post(`${apiUrl}/api/auth/login`, {
      data: { loginId: this.#loginId, password: this.#password },
    });
    expect(response.status(), "The actual backend must accept the doctor login.").toBe(200);
    return sessionIdentityFromLogin(await response.json(), "doctor");
  }

  async connect(page: Page, doctorUrl: string): Promise<LoginSessionIdentity> {
    await page.goto(`${doctorUrl}/#/doctor`);
    await page.getByRole("button", { name: "로그인", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "의사 로그인", exact: true });
    await expect(dialog).toBeVisible();
    await dialog.getByLabel("의사 아이디").fill(this.#loginId);
    await dialog.getByLabel("비밀번호").fill(this.#password);
    const loginResponse = page.waitForResponse((r) =>
      new URL(r.url()).pathname === "/api/auth/login" && r.request().method() === "POST");
    const listResponse = page.waitForResponse((r) =>
      new URL(r.url()).pathname === "/api/cases" && r.request().method() === "GET");
    await dialog.getByRole("button", { name: "로그인", exact: true }).click();
    // Await both even when login fails so no response waiter is left unhandled.
    const [login, list] = await Promise.all([loginResponse, listResponse]);
    const identity = await sessionFromUiResponse(login, "doctor");
    expect(list.status(), "Doctor login must grant access to the assigned case list.").toBe(200);
    await expect(dialog).toBeHidden();
    return identity;
  }
}

export function doctorIdentityFromEnvironment(env: NodeJS.ProcessEnv = process.env): DoctorLoginIdentity {
  // The old variable is still a CD credential transport, never a demo bearer token.
  const password = env.SKINAI_E2E_DOCTOR_PASSWORD ?? env.SKINAI_E2E_DOCTOR_TOKEN;
  if (password === undefined) {
    throw new Error("Missing required isolated-test doctor password setting.");
  }
  return new DoctorLoginIdentity(env.SKINAI_E2E_DOCTOR_LOGIN ?? "ci-doctor", password);
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
