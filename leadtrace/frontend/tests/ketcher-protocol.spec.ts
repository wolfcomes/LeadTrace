import { describe, expect, it } from "vitest";

import {
  KETCHER_MESSAGE_PROTOCOL,
  KETCHER_MESSAGE_VERSION,
  createChildMessage,
  createSetMoleculeMessage,
  parseChildMessage,
  parseParentMessage,
} from "../src/review/paper/ketcherProtocol";

describe("Ketcher message protocol", () => {
  it("creates and parses the one supported parent command", () => {
    const message = createSetMoleculeMessage("CCO");

    expect(message).toEqual({
      protocol: KETCHER_MESSAGE_PROTOCOL,
      version: KETCHER_MESSAGE_VERSION,
      kind: "set-molecule",
      molecule: "CCO",
    });
    expect(parseParentMessage(message)).toEqual(message);
  });

  it("creates and parses ready, Molfile, and error child messages", () => {
    const ready = createChildMessage("ready");
    const molfile = createChildMessage("molfile", "MOLFILE");
    const error = createChildMessage("error", "Unable to export");

    expect(parseChildMessage(ready)).toEqual(ready);
    expect(parseChildMessage(molfile)).toEqual(molfile);
    expect(parseChildMessage(error)).toEqual(error);
  });

  it.each([
    null,
    [],
    { protocol: "wrong", version: KETCHER_MESSAGE_VERSION, kind: "ready" },
    { protocol: KETCHER_MESSAGE_PROTOCOL, version: 2, kind: "ready" },
    { protocol: KETCHER_MESSAGE_PROTOCOL, version: KETCHER_MESSAGE_VERSION, kind: "unknown" },
    { protocol: KETCHER_MESSAGE_PROTOCOL, version: KETCHER_MESSAGE_VERSION, kind: "molfile", molfile: 42 },
    { protocol: KETCHER_MESSAGE_PROTOCOL, version: KETCHER_MESSAGE_VERSION, kind: "error", message: "bad", token: "secret" },
  ])("rejects malformed child payload %#", (payload) => {
    expect(parseChildMessage(payload)).toBeNull();
  });

  it.each([
    undefined,
    { protocol: KETCHER_MESSAGE_PROTOCOL, version: KETCHER_MESSAGE_VERSION, kind: "set-molecule" },
    { protocol: KETCHER_MESSAGE_PROTOCOL, version: KETCHER_MESSAGE_VERSION, kind: "set-molecule", molecule: 42 },
    { protocol: KETCHER_MESSAGE_PROTOCOL, version: KETCHER_MESSAGE_VERSION, kind: "set-molecule", molecule: "CCO", csrf: "secret" },
  ])("rejects malformed parent payload %#", (payload) => {
    expect(parseParentMessage(payload)).toBeNull();
  });
});
