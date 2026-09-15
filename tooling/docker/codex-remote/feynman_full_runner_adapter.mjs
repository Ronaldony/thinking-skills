#!/usr/bin/env node
/**
 * Fixed MCP adapter for the full-runner contract.
 *
 * The model may read candidate.py, provide candidate.py contents, or request
 * the fixed test. It cannot select a path, shell, executable, argv, image, or
 * network mode. Test execution is an argv-based Docker invocation with a
 * read-only root and --network none.
 */

import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import readline from "node:readline";

const ROOT_ENV = "FEYNMAN_FULL_RUNNER_ROOT";
const DOCKER_ENV = "FEYNMAN_FULL_RUNNER_DOCKER";
const DOCKER_CONFIG_ENV = "FEYNMAN_FULL_RUNNER_DOCKER_CONFIG";
const IMAGE_ENV = "FEYNMAN_FULL_RUNNER_IMAGE";
const CANDIDATE_FILE = "candidate.py";
const TEST_FILE = "test_candidate.py";
const CONTAINER_ROOT = "/run/candidate";
const READ_TOOL = "feynman_read_candidate";
const WRITE_TOOL = "feynman_write_candidate";
const TEST_TOOL = "feynman_run_tests";
const MAX_CALLS = Object.freeze({ [READ_TOOL]: 8, [WRITE_TOOL]: 8, [TEST_TOOL]: 8 });
const READ_LIMIT_BYTES = 131072;
const WRITE_LIMIT_BYTES = 131072;
const TEST_OUTPUT_LIMIT_BYTES = 32768;
const TEST_TIMEOUT_MS = 60000;
const RETIRED_AUTH_ENV_KEYS = ["OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN"];

function fail(message) {
  throw new Error(message);
}

function requireAbsolute(value, label) {
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
    if (stat.isSymbolicLink()) fail(`${label} contains a symbolic link`);
  }
}

function regularFile(root, name, label) {
  const target = path.join(root, name);
  inspectNoSymlink(target, label);
  const stat = fs.statSync(target);
  if (!stat.isFile()) fail(`${label} is not a regular file`);
  return target;
}

function loadPolicy() {
  for (const key of RETIRED_AUTH_ENV_KEYS) {
    if (Object.prototype.hasOwnProperty.call(process.env, key)) {
      fail("retired authentication environment is not allowed");
    }
  }
  const root = requireAbsolute(process.env[ROOT_ENV], "full-runner root");
  const docker = requireAbsolute(process.env[DOCKER_ENV], "Docker executable");
  const dockerConfig = requireAbsolute(process.env[DOCKER_CONFIG_ENV], "Docker config");
  const image = process.env[IMAGE_ENV];
  if (typeof image !== "string" || !/^sha256:[0-9a-f]{64}$/.test(image)) {
    fail("full-runner image must be content-addressed");
  }
  inspectNoSymlink(root, "full-runner root");
  inspectNoSymlink(docker, "Docker executable");
  inspectNoSymlink(dockerConfig, "Docker config");
  if (!fs.statSync(root).isDirectory() || !fs.statSync(docker).isFile() ||
      !fs.statSync(dockerConfig).isDirectory()) {
    fail("full-runner policy path is not the required type");
  }
  return {
    root,
    candidate: regularFile(root, CANDIDATE_FILE, "candidate source file"),
    test: regularFile(root, TEST_FILE, "fixed candidate test file"),
    docker,
    dockerConfig,
    image,
  };
}

function response(id, result) {
  return { jsonrpc: "2.0", id, result };
}

function errorResponse(id, message) {
  return { jsonrpc: "2.0", id: id ?? null, error: { code: -32001, message } };
}

function write(message) {
  process.stdout.write(`${JSON.stringify(message)}\n`);
}

function validEmptyArguments(args) {
  return args === undefined || (typeof args === "object" && args !== null &&
    !Array.isArray(args) && Object.keys(args).length === 0);
}

function boundedText(buffer) {
  const truncated = buffer.length > TEST_OUTPUT_LIMIT_BYTES;
  const value = buffer.subarray(0, TEST_OUTPUT_LIMIT_BYTES).toString("utf8");
  return { value, truncated };
}

function appendBounded(chunks, chunk, state) {
  const before = state.total;
  if (state.total < TEST_OUTPUT_LIMIT_BYTES) {
    const remaining = TEST_OUTPUT_LIMIT_BYTES - state.total;
    const selected = chunk.subarray(0, remaining);
    chunks.push(selected);
    state.total += selected.length;
  }
  if (chunk.length > state.total - before) state.truncated = true;
}

function runFixedTests(policy) {
  return new Promise((resolve) => {
    const args = [
      "--config", policy.dockerConfig,
      "run", "--rm",
      "--network", "none",
      "--cap-drop", "ALL",
      "--security-opt", "no-new-privileges",
      "--read-only",
      "--user", "1000:1000",
      "--tmpfs", "/tmp:rw,nosuid,nodev",
      "--volume", `${policy.root}:${CONTAINER_ROOT}:ro`,
      "--workdir", CONTAINER_ROOT,
      policy.image,
      "env", "-i",
      "HOME=/tmp",
      "PATH=/usr/local/bin:/usr/bin:/bin",
      "PYTHONDONTWRITEBYTECODE=1",
      "python3", "-B", "-I", `${CONTAINER_ROOT}/${TEST_FILE}`,
    ];
    let child;
    try {
      child = spawn(policy.docker, args, { stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
    } catch {
      resolve({ started: false, exitCode: null, timedOut: false, stdout: "", stderr: "" });
      return;
    }
    const stdout = [], stderr = [];
    const stdoutState = { total: 0, truncated: false };
    const stderrState = { total: 0, truncated: false };
    child.stdout.on("data", (chunk) => appendBounded(stdout, Buffer.from(chunk), stdoutState));
    child.stderr.on("data", (chunk) => appendBounded(stderr, Buffer.from(chunk), stderrState));
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill();
    }, TEST_TIMEOUT_MS);
    child.on("error", () => {
      clearTimeout(timer);
      resolve({ started: false, exitCode: null, timedOut, stdout: "", stderr: "" });
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({
        started: true,
        exitCode: typeof code === "number" ? code : null,
        timedOut,
        stdout: Buffer.concat(stdout).toString("utf8"),
        stderr: Buffer.concat(stderr).toString("utf8"),
        stdoutTruncated: stdoutState.truncated,
        stderrTruncated: stderrState.truncated,
      });
    });
  });
}

let policy;
try {
  policy = loadPolicy();
} catch {
  process.stderr.write("feynman full-runner adapter configuration failed\n");
  process.exit(2);
}

const calls = { [READ_TOOL]: 0, [WRITE_TOOL]: 0, [TEST_TOOL]: 0 };
const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
input.on("line", async (line) => {
  let message;
  try {
    message = JSON.parse(line);
  } catch {
    write(errorResponse(null, "invalid JSON-RPC message"));
    return;
  }
  const { id, method, params } = message;
  if (method === "notifications/initialized") return;
  if (method === "initialize") {
    write(response(id, {
      protocolVersion: "2024-11-05",
      capabilities: { tools: {} },
      serverInfo: { name: "feynman-full-runner", version: "0.1.0" },
    }));
    return;
  }
  if (method === "tools/list") {
    write(response(id, {
      tools: [
        { name: READ_TOOL, description: "Read the fixed candidate.py file.", inputSchema: { type: "object", properties: {}, additionalProperties: false } },
        { name: WRITE_TOOL, description: "Write only candidate.py with the supplied UTF-8 content.", inputSchema: { type: "object", properties: { content: { type: "string", maxLength: WRITE_LIMIT_BYTES } }, required: ["content"], additionalProperties: false } },
        { name: TEST_TOOL, description: "Run the fixed test_candidate.py command in a network-disabled Docker container.", inputSchema: { type: "object", properties: {}, additionalProperties: false } },
      ],
    }));
    return;
  }
  if (method !== "tools/call" || !params || typeof params.name !== "string") {
    write(errorResponse(id, "method not supported"));
    return;
  }
  const name = params.name;
  if (!Object.prototype.hasOwnProperty.call(calls, name)) {
    write(errorResponse(id, "full-runner tool name rejected"));
    return;
  }
  if (calls[name] >= MAX_CALLS[name]) {
    write(errorResponse(id, "full-runner tool call limit reached"));
    return;
  }
  if (name === READ_TOOL) {
    if (!validEmptyArguments(params.arguments)) {
      write(errorResponse(id, "candidate read arguments rejected"));
      return;
    }
    calls[name] += 1;
    try {
      inspectNoSymlink(policy.candidate, "candidate source file");
      const data = fs.readFileSync(policy.candidate);
      if (data.length > READ_LIMIT_BYTES) {
        write(errorResponse(id, "candidate source exceeds fixed read limit"));
        return;
      }
      write(response(id, {
        content: [{ type: "text", text: JSON.stringify({ file: CANDIDATE_FILE, bytesRead: data.length, source: data.toString("utf8") }) }],
        isError: false,
      }));
    } catch {
      write(errorResponse(id, "candidate read failed"));
    }
    return;
  }
  if (name === WRITE_TOOL) {
    const args = params.arguments;
    if (!args || typeof args !== "object" || Array.isArray(args) ||
        Object.keys(args).length !== 1 || typeof args.content !== "string") {
      write(errorResponse(id, "candidate write arguments rejected"));
      return;
    }
    const bytes = Buffer.byteLength(args.content, "utf8");
    if (bytes > WRITE_LIMIT_BYTES) {
      write(errorResponse(id, "candidate write exceeds fixed byte limit"));
      return;
    }
    calls[name] += 1;
    try {
      inspectNoSymlink(policy.candidate, "candidate source file");
      fs.writeFileSync(policy.candidate, args.content, { encoding: "utf8", flag: "w" });
      inspectNoSymlink(policy.candidate, "candidate source file");
      write(response(id, {
        content: [{ type: "text", text: JSON.stringify({ file: CANDIDATE_FILE, bytesWritten: bytes, verdict: "candidate-written" }) }],
        isError: false,
      }));
    } catch {
      write(errorResponse(id, "candidate write failed"));
    }
    return;
  }
  if (!validEmptyArguments(params.arguments)) {
    write(errorResponse(id, "fixed test arguments rejected"));
    return;
  }
  calls[name] += 1;
  const result = await runFixedTests(policy);
  const stdout = boundedText(Buffer.from(result.stdout || "", "utf8"));
  const stderr = boundedText(Buffer.from(result.stderr || "", "utf8"));
  const passed = result.started && !result.timedOut && result.exitCode === 0;
  write(response(id, {
    content: [{ type: "text", text: JSON.stringify({
      file: TEST_FILE,
      networkMode: "none",
      started: result.started,
      timedOut: result.timedOut,
      exitCode: result.exitCode,
      passed,
      stdout: stdout.value,
      stderr: stderr.value,
      outputTruncated: stdout.truncated || stderr.truncated || result.stdoutTruncated || result.stderrTruncated,
    }) }],
    isError: !passed,
  }));
});
