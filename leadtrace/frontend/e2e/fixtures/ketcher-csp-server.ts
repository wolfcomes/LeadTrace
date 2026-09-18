import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createServer, type ServerResponse } from "node:http";
import { dirname, extname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const STRICT_CSP = "default-src 'self'; connect-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; font-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'";
const KETCHER_CSP = "default-src 'self'; connect-src 'self' blob:; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-eval'; worker-src 'self' blob:; font-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'self'; form-action 'none'";

const parentHtml = `<!doctype html>
<html lang="en">
  <head><meta charset="UTF-8"><title>Ketcher CSP harness</title></head>
  <body>
    <iframe id="ketcher" src="/ketcher.html" title="Ketcher"></iframe>
    <output id="status">loading</output>
    <script src="/test-parent.js" defer></script>
  </body>
</html>`;

const parentScript = `(() => {
  const protocol = "leadtrace-ketcher-v1";
  const version = 1;
  const iframe = document.querySelector("#ketcher");
  const status = document.querySelector("#status");
  window.ketcherHarness = { ready: false, molfile: "", errors: [] };
  window.addEventListener("message", (event) => {
    if (event.origin !== window.location.origin || event.source !== iframe.contentWindow) return;
    const message = event.data;
    if (!message || message.protocol !== protocol || message.version !== version) return;
    if (message.kind === "ready") {
      window.ketcherHarness.ready = true;
      status.value = "ready";
      iframe.contentWindow.postMessage(
        { protocol, version, kind: "set-molecule", requestId: 1, molecule: "CCO" },
        window.location.origin,
      );
    } else if (message.kind === "molfile" && message.requestId === 1 && typeof message.molfile === "string") {
      window.ketcherHarness.molfile = message.molfile;
      status.value = "molfile";
    } else if (message.kind === "error" && typeof message.message === "string") {
      window.ketcherHarness.errors.push(message.message);
      status.value = "error";
    }
  });
})();`;

const contentTypes: Record<string, string> = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".wasm": "application/wasm",
  ".woff2": "font/woff2",
};

function applySecurityHeaders(response: ServerResponse, ketcher: boolean): void {
  response.setHeader("Content-Security-Policy", ketcher ? KETCHER_CSP : STRICT_CSP);
  response.setHeader("X-Content-Type-Options", "nosniff");
  response.setHeader("X-Frame-Options", ketcher ? "SAMEORIGIN" : "DENY");
}

export interface KetcherCspServer {
  origin: string;
  close(): Promise<void>;
}

export async function startKetcherCspServer(): Promise<KetcherCspServer> {
  const fixtureDirectory = dirname(fileURLToPath(import.meta.url));
  const distDirectory = resolve(fixtureDirectory, "../../dist");
  await stat(resolve(distDirectory, "index.html"));
  await stat(resolve(distDirectory, "ketcher.html"));

  const server = createServer(async (request, response) => {
    const requestUrl = new URL(request.url ?? "/", "http://127.0.0.1");
    const pathname = decodeURIComponent(requestUrl.pathname);
    if (pathname === "/test-parent.html") {
      applySecurityHeaders(response, false);
      response.writeHead(200, { "Content-Type": contentTypes[".html"] });
      response.end(parentHtml);
      return;
    }
    if (pathname === "/test-parent.js") {
      applySecurityHeaders(response, false);
      response.writeHead(200, { "Content-Type": contentTypes[".js"] });
      response.end(parentScript);
      return;
    }

    const requestedFile = pathname === "/" ? "/index.html" : pathname;
    const filePath = resolve(distDirectory, `.${requestedFile}`);
    if (!filePath.startsWith(`${distDirectory}${sep}`)) {
      response.writeHead(403);
      response.end();
      return;
    }
    try {
      const file = await stat(filePath);
      if (!file.isFile()) throw new Error("not a file");
      applySecurityHeaders(response, pathname === "/ketcher.html");
      response.writeHead(200, {
        "Content-Type": contentTypes[extname(filePath)] ?? "application/octet-stream",
      });
      createReadStream(filePath).pipe(response);
    } catch {
      response.writeHead(404);
      response.end();
    }
  });

  await new Promise<void>((resolveListen, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      server.off("error", reject);
      resolveListen();
    });
  });
  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("CSP fixture server did not bind a TCP port");
  }

  return {
    origin: `http://127.0.0.1:${address.port}`,
    close: () => new Promise<void>((resolveClose, reject) => {
      server.close((error) => error ? reject(error) : resolveClose());
    }),
  };
}
