import { expect, test } from "@playwright/test";
import { inspect } from "node:util";
import {
  DemoDoctorIdentity, doctorIdentityFromEnvironment, patientIdentityFromIntake,
} from "../support/auth";

// Disposable strings only. These tests check adapter behavior, NOT actual login.
const PATIENT_TOKEN = "disposable-patient-token-for-helper-check";
const DOCTOR_TOKEN = "disposable-doctor-token-for-helper-check";

test("helper: patient and doctor keep separate credentials", () => {
  const patient = patientIdentityFromIntake({ id: "helper-case-1", accessToken: PATIENT_TOKEN });
  const doctor = doctorIdentityFromEnvironment({ SKINAI_E2E_DOCTOR_TOKEN: DOCTOR_TOKEN });
  expect(patient.caseId).toBe("helper-case-1");
  expect(patient.role).toBe("patient");
  expect(doctor.role).toBe("doctor");
  expect(patient.requestOptions().headers.Authorization === `Bearer ${PATIENT_TOKEN}`).toBe(true);
  expect(doctor.requestOptions().headers.Authorization === `Bearer ${DOCTOR_TOKEN}`).toBe(true);
});

test("helper: credentials are absent from object serialization and inspection", () => {
  const identities = [
    patientIdentityFromIntake({ id: "helper-case-2", accessToken: PATIENT_TOKEN }),
    new DemoDoctorIdentity(DOCTOR_TOKEN),
  ];
  for (const identity of identities) {
    const diagnostic = JSON.stringify(identity) + inspect(identity);
    expect(diagnostic.includes(PATIENT_TOKEN) || diagnostic.includes(DOCTOR_TOKEN)).toBe(false);
  }
});

test("helper: mutating one request cannot change a later request", () => {
  const identity = new DemoDoctorIdentity(DOCTOR_TOKEN);
  const first = identity.requestOptions();
  first.headers.Authorization = "Bearer unrelated-disposable-value";
  expect(identity.requestOptions().headers.Authorization === `Bearer ${DOCTOR_TOKEN}`).toBe(true);
});

test("helper: incomplete intake responses fail without echoing payloads", () => {
  const invalid = [null, [], {}, { id: 17, accessToken: PATIENT_TOKEN },
    { id: "", accessToken: PATIENT_TOKEN }, { id: "case", accessToken: "" }];
  for (const value of invalid) {
    let message = "";
    try { patientIdentityFromIntake(value); } catch (error) { message = String(error); }
    expect(message.length).toBeGreaterThan(0);
    expect(message.includes(PATIENT_TOKEN)).toBe(false);
  }
});

test("helper: blank or malformed doctor credentials fail without fallback", () => {
  expect(() => doctorIdentityFromEnvironment({})).toThrow(/Missing required isolated-test setting/);
  for (const token of ["", " ", "value\n", "value\r", "value\r\n", "value\nInjected: header", "Bearer already-prefixed"]) {
    expect(() => new DemoDoctorIdentity(token)).toThrow(/nonempty current-contract test token/);
  }
});
