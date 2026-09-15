#!/usr/bin/env node
/**
 * A deliberately tiny, model-facing MCP server for the one-byte diagnostic.
 *
 * The configured file is fixed by the evaluator environment. The tool accepts
 * no path, offset, command, or free-form selector from the model. It performs
 * at most one read of at most one byte and returns only that byte as base64.
 * This is a diagnostic adapter, not a general filesystem tool.
 */

import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";

const ROOT_ENV = "FEYNMAN_BOUNDED_READ_ROOT";
const FILE_ENV = "FEYNMAN_BOUNDED_READ_FILE";
const TOOL_NAME = "feynman_read_probe_byte";
const MAX_CALLS = 1;
const MAX_BYTES = 1;

function fail(message) {
  throw new Error(message);
}

function absolutePath(value, label) {
  if (typeof value !== "string" || value.length === 0 || !path.isAbsolute(value)) {
    fail(`${label} must be an absolute path`);
  }
  return path.normalize(value);
}

function inspectNoSymlink(value, label) {
  const parsed = path.parse(value);
  const parts = value.slice(parsed.root.length).split(path.sep).filter(Boolean);
  let current = parsed.root;
  for (const part of parts) {
    current = path.join(current, part);
    let stat;
    try {
      stat = fs.lstatSync(current);
    } catch {
      fail(`${label} does not exist`);
    }
    if (stat.isSymbolicLink()) {
      fail(`${label} contains a symbolic link`);
    }
  }
}

function loadPolicy() {
  const root = absolutePath(process.env[ROOT_ENV], "bounded read root");
  const file = absolutePath(process.env[FILE_ENV], "bounded read file");
  const relative = path.relative(root, file);
  if (relative === "" || relative === ".." || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) {
    fail("bounded read file is outside the configured root");
  }
  inspectNoSymlink(root, "bounded read root");
  inspectNoSymlink(file, "bounded read file");
  const rootStat = fs.statSync(root);
  const fileStat = fs.statSync(file);
  if (!rootStat.isDirectory() || !fileStat.isFile()) {
    fail("bounded read target is not a regular file under a directory root");
  }
  return { root, file };
}

function response(id, result) {
  return { jsonrpc: "2.0", id, result };
}

function errorResponse(id, message) {
  return {
    jsonrpc: "2.0",
    id: id ?? null,
    error: { code: -32001, message },
  };
}

function write(message) {
  process.stdout.write(`${JSON.stringify(message)}\n`);
}

let policy;
try {
  policy = loadPolicy();
} catch {
  process.stderr.write("feynman bounded read adapter configuration failed\n");
  process.exit(2);
}

let calls = 0;
const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
input.on("line", (line) => {
  let message;
  try {
    message = JSON.parse(line);
  } catch {
    write(errorResponse(null, "invalid JSON-RPC message"));
    return;
  }
  const { id, method, params } = message;
  if (method === "notifications/initialized") {
    return;
  }
  if (method === "initialize") {
    write(response(id, {
      protocolVersion: "2024-11-05",
      capabilities: { tools: {} },
      serverInfo: { name: "feynman-bounded-read", version: "0.1.0" },
    }));
    return;
  }
  if (method === "tools/list") {
    write(response(id, {
      tools: [{
        name: TOOL_NAME,
        description: "Read the fixed diagnostic fixture once, returning at most one byte.",
        inputSchema: { type: "object", properties: {}, additionalProperties: false },
      }],
    }));
    return;
  }
  if (method !== "tools/call") {
    write(errorResponse(id, "method not supported"));
    return;
  }
  if (!params || params.name !== TOOL_NAME ||
      (params.arguments !== undefined &&
       (typeof params.arguments !== "object" || params.arguments === null ||
        Array.isArray(params.arguments) || Object.keys(params.arguments).length !== 0))) {
    write(errorResponse(id, "bounded read tool arguments rejected"));
    return;
  }
  if (calls >= MAX_CALLS) {
    write(errorResponse(id, "bounded read call limit reached"));
    return;
  }
  calls += 1;
  try {
    const fd = fs.openSync(policy.file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0));
    try {
      const buffer = Buffer.alloc(MAX_BYTES);
      const count = fs.readSync(fd, buffer, 0, MAX_BYTES, 0);
      if (count < 0 || count > MAX_BYTES) {
        throw new Error("bounded read returned an invalid size");
      }
      write(response(id, {
        content: [{ type: "text", text: JSON.stringify({
          byteBase64: buffer.subarray(0, count).toString("base64"),
          bytesRead: count,
        }) }],
        isError: false,
      }));
    } finally {
      fs.closeSync(fd);
    }
  } catch {
    write(errorResponse(id, "bounded read failed"));
  }
});
