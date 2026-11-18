import { expect, test } from "@playwright/test";
import { inspect } from "node:util";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import {
  DoctorLoginIdentity, doctorIdentityFromEnvironment, patientIdentityFromIntake,
  sessionIdentityFromLogin,
} from "../support/auth";

// These exercise the shared adapter, not the application's authentication logic.
// Application login/lockout/revocation is tested against the real isolated API.
const SESSION_TOKEN = "disposable-session-token-for-helper-check";
const CASE_TOKEN = "disposable-case-token-for-helper-check";
const PASSWORD = "disposable-password-for-helper-check";
const doctorReply = () => ({ accessToken: SESSION_TOKEN, expiresAt: 1794950000,
  loginId: "ci-doctor", name: "검사의사", role: "doctor", doctorId: "d1" });

async function listen(server: Server): Promise<string> {
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  return `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
}
async function close(server: Server) {
  server.closeAllConnections();
  await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
}

test("helper: case credentials and login sessions remain distinct", () => {
  const legacyCase = patientIdentityFromIntake({ id: "helper-case-1", accessToken: CASE_TOKEN });
  const patient = sessionIdentityFromLogin({ ...doctorReply(), role: "patient", doctorId: null,
    loginId: "01012345678" }, "patient");
  const doctor = sessionIdentityFromLogin(doctorReply(), "doctor");
  expect(legacyCase.caseId).toBe("helper-case-1");
  expect(legacyCase.kind).toBe("case");
  expect(patient.kind).toBe("session");
  expect(patient.role).toBe("patient");
  expect(doctor.doctorId).toBe("d1");
  expect(legacyCase.requestOptions().headers.Authorization === `Bearer ${CASE_TOKEN}`).toBe(true);
  expect(doctor.requestOptions().headers.Authorization === `Bearer ${SESSION_TOKEN}`).toBe(true);
});

test("helper: credentials are absent from object serialization and inspection", () => {
  const identities = [
    patientIdentityFromIntake({ id: "helper-case-2", accessToken: CASE_TOKEN }),
    sessionIdentityFromLogin(doctorReply(), "doctor"),
    new DoctorLoginIdentity("ci-doctor", PASSWORD),
  ];
  for (const identity of identities) {
    const diagnostic = JSON.stringify(identity) + inspect(identity);
    expect([CASE_TOKEN, SESSION_TOKEN, PASSWORD].some((secret) => diagnostic.includes(secret))).toBe(false);
  }
});

test("helper: mutating one request cannot change a later request", () => {
  const identity = sessionIdentityFromLogin(doctorReply(), "doctor");
  const first = identity.requestOptions();
  first.headers.Authorization = "Bearer unrelated-disposable-value";
  expect(identity.requestOptions().headers.Authorization === `Bearer ${SESSION_TOKEN}`).toBe(true);
});

test("helper: incomplete or mismatched login replies fail without leaking payloads", () => {
  const invalid = [null, [], {}, { ...doctorReply(), role: "patient" },
    { ...doctorReply(), doctorId: null }, { ...doctorReply(), expiresAt: "1794950000" },
    { ...doctorReply(), expiresAt: NaN }, { ...doctorReply(), name: "" },
    { ...doctorReply(), accessToken: "" }];
  for (const value of invalid) {
    let message = "";
    try { sessionIdentityFromLogin(value, "doctor"); } catch (error) { message = String(error); }
    expect(message.length).toBeGreaterThan(0);
    expect(message.includes(SESSION_TOKEN)).toBe(false);
  }
  for (const token of [" ", "value\n", "value\r", "value\r\n", "value\nInjected: header", "Bearer already-prefixed"]) {
    expect(() => sessionIdentityFromLogin({ ...doctorReply(), accessToken: token }, "doctor"))
      .toThrow(/valid test access token/);
  }
});

test("helper: incomplete case replies still fail safely", () => {
  for (const value of [null, [], {}, { id: 17, accessToken: CASE_TOKEN },
    { id: "", accessToken: CASE_TOKEN }, { id: "case", accessToken: "" }]) {
    let message = "";
    try { patientIdentityFromIntake(value); } catch (error) { message = String(error); }
    expect(message.length).toBeGreaterThan(0);
    expect(message.includes(CASE_TOKEN)).toBe(false);
  }
});

test("helper: missing or blank configured password never falls back", () => {
  expect(() => doctorIdentityFromEnvironment({})).toThrow(/Missing required/);
  expect(() => doctorIdentityFromEnvironment({ SKINAI_E2E_DOCTOR_PASSWORD: "", SKINAI_E2E_DOCTOR_TOKEN: PASSWORD }))
    .toThrow(/login credentials/);
  for (const password of ["", " ", "value\n", "value\r", "value\0"]) {
    expect(() => new DoctorLoginIdentity("ci-doctor", password)).toThrow(/login credentials/);
  }
});

test("helper: legacy CD setting supplies a login password and logout sends the returned session", async ({ request }) => {
  const calls: { path: string; method: string | undefined; loginMatches: boolean; bearerMatches: boolean }[] = [];
  const server = createServer(async (incoming, outgoing) => {
    let raw = "";
    for await (const chunk of incoming) raw += chunk.toString();
    const body = raw ? JSON.parse(raw) as Record<string, unknown> : {};
    calls.push({ path: incoming.url!, method: incoming.method,
      loginMatches: body.loginId === "ci-doctor" && body.password === PASSWORD,
      bearerMatches: incoming.headers.authorization === `Bearer ${SESSION_TOKEN}` });
    if (incoming.url === "/api/auth/login") {
      outgoing.writeHead(200, { "Content-Type": "application/json" });
      outgoing.end(JSON.stringify(doctorReply()));
    } else { outgoing.writeHead(204); outgoing.end(); }
  });
  const apiUrl = await listen(server);
  try {
    const credentials = doctorIdentityFromEnvironment({ SKINAI_E2E_DOCTOR_TOKEN: PASSWORD });
    const session = await credentials.login(request, apiUrl);
    await session.logout(request, apiUrl);
    expect(calls).toEqual([
      { path: "/api/auth/login", method: "POST", loginMatches: true, bearerMatches: false },
      { path: "/api/auth/logout", method: "POST", loginMatches: false, bearerMatches: true },
    ]);
  } finally { await close(server); }
});

test("helper: rejected doctor login makes no legacy retry", async ({ request }) => {
  const paths: string[] = [];
  const server = createServer((incoming, outgoing) => {
    paths.push(incoming.url!);
    incoming.resume();
    outgoing.writeHead(401, { "Content-Type": "application/json" });
    outgoing.end(JSON.stringify({ detail: "rejected", request_id: "helper" }));
  });
  const apiUrl = await listen(server);
  try {
    let rejected = false;
    try { await new DoctorLoginIdentity("ci-doctor", PASSWORD).login(request, apiUrl); }
    catch { rejected = true; }
    expect(rejected).toBe(true);
    expect(paths).toEqual(["/api/auth/login"]);
  } finally { await close(server); }
});
