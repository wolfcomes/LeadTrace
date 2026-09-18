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
    const message = createSetMoleculeMessage(7, "CCO");

    expect(message).toEqual({
      protocol: KETCHER_MESSAGE_PROTOCOL,
      version: KETCHER_MESSAGE_VERSION,
      kind: "set-molecule",
      requestId: 7,
      molecule: "CCO",
    });
    expect(parseParentMessage(message)).toEqual(message);
  });

  it("creates and parses ready, Molfile, and error child messages", () => {
    const ready = createChildMessage("ready");
    const molfile = createChildMessage("molfile", 7, "MOLFILE");
    const error = createChildMessage("error", 7, "Unable to export");

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
    { protocol: KETCHER_MESSAGE_PROTOCOL, version: KETCHER_MESSAGE_VERSION, kind: "molfile", requestId: 1, molfile: 42 },
    { protocol: KETCHER_MESSAGE_PROTOCOL, version: KETCHER_MESSAGE_VERSION, kind: "error", requestId: 1, message: "bad", token: "secret" },
  ])("rejects malformed child payload %#", (payload) => {
    expect(parseChildMessage(payload)).toBeNull();
  });

  it.each([
    undefined,
    { protocol: KETCHER_MESSAGE_PROTOCOL, version: KETCHER_MESSAGE_VERSION, kind: "set-molecule" },
    { protocol: KETCHER_MESSAGE_PROTOCOL, version: KETCHER_MESSAGE_VERSION, kind: "set-molecule", requestId: 0, molecule: "CCO" },
    { protocol: KETCHER_MESSAGE_PROTOCOL, version: KETCHER_MESSAGE_VERSION, kind: "set-molecule", requestId: 1, molecule: 42 },
    { protocol: KETCHER_MESSAGE_PROTOCOL, version: KETCHER_MESSAGE_VERSION, kind: "set-molecule", requestId: 1, molecule: "CCO", csrf: "secret" },
  ])("rejects malformed parent payload %#", (payload) => {
    expect(parseParentMessage(payload)).toBeNull();
  });
});
